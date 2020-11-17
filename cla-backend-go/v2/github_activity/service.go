// Copyright The Linux Foundation and each contributor to CommunityBridge.
// SPDX-License-Identifier: MIT

package github_activity

import (
	"context"
	"errors"
	"fmt"
	"strconv"
	"strings"

	githubutils "github.com/communitybridge/easycla/cla-backend-go/github"

	"github.com/communitybridge/easycla/cla-backend-go/utils"

	"github.com/communitybridge/easycla/cla-backend-go/gen/models"

	"github.com/communitybridge/easycla/cla-backend-go/v2/dynamo_events"

	"github.com/communitybridge/easycla/cla-backend-go/events"

	"github.com/communitybridge/easycla/cla-backend-go/repositories"

	log "github.com/communitybridge/easycla/cla-backend-go/logging"
	"github.com/google/go-github/v32/github"
)

// Service is responsible for handling the github activity events
type Service interface {
	ProcessInstallationRepositoriesEvent(event *github.InstallationRepositoriesEvent) error
	ProcessRepositoryEvent(*github.RepositoryEvent) error
	ProcessPullRequestComment(event *github.IssueCommentEvent) error
}

type eventHandlerService struct {
	githubRepo        repositories.Repository
	githubOrgRepo     repositories.GithubOrgRepo
	eventService      events.Service
	autoEnableService dynamo_events.AutoEnableService
}

// NewService creates a new instance of the Event Handler Service
func NewService(githubRepo repositories.Repository,
	eventService events.Service,
	autoEnableService dynamo_events.AutoEnableService) Service {
	return &eventHandlerService{
		githubRepo:        githubRepo,
		eventService:      eventService,
		autoEnableService: autoEnableService,
	}
}

func (s *eventHandlerService) ProcessRepositoryEvent(event *github.RepositoryEvent) error {
	log.Debugf("ProcessRepositoryEvent called for action : %s", *event.Action)
	if event.Action == nil {
		return fmt.Errorf("no action found in event payload")
	}
	switch *event.Action {
	case "created":
		return s.handleRepositoryAddedAction(event.Sender, event.Repo)
	case "deleted":
		return s.handleRepositoryRemovedAction(event.Sender, event.Repo)
	default:
		log.Warnf("ProcessRepositoryEvent no handler for action : %s", *event.Action)
	}

	return nil

}

func (s *eventHandlerService) ProcessPullRequestComment(event *github.IssueCommentEvent) error {
	log.Debugf("ProcessPullRequestComment called for action : %s", *event.Action)
	if event.Action == nil {
		return fmt.Errorf("no action found in event payload")
	}
	switch *event.Action {
	case "created", "edited":
		return s.handlePullRequestComment(event)
	default:
		log.Warnf("ProcessPullRequestComment no handler for action : %s", *event.Action)
	}

	return nil
}

func (s *eventHandlerService) handleRepositoryAddedAction(sender *github.User, repo *github.Repository) error {
	if repo.ID == nil || *repo.ID == 0 {
		return fmt.Errorf("missing repo id")
	}

	if repo.Name == nil || *repo.Name == "" {
		return fmt.Errorf("repo name is missing")
	}

	if repo.FullName == nil || *repo.FullName == "" {
		return fmt.Errorf("repo full name missing")
	}
	repoModel, err := s.autoEnableService.CreateAutoEnabledRepository(repo)
	if err != nil {
		if errors.Is(err, dynamo_events.ErrAutoEnabledOff) {
			log.Warnf("autoEnable is off for this repo : %s can't continue", *repo.FullName)
			return nil
		}
		return err
	}

	if err := s.autoEnableService.NotifyCLAManagerForRepos(repoModel.RepositoryProjectID, []*models.GithubRepository{repoModel}); err != nil {
		log.Warnf("notifyCLAManager for autoEnabled repo : %s for claGroup : %s failed : %v", repoModel.RepositoryName, repoModel.RepositoryProjectID, err)
	}

	if sender == nil || sender.Login == nil || *sender.Login == "" {
		log.Warnf("not able to send event empty sender")
		return nil
	}

	// sending the log event for the added repository
	log.Debugf("handleRepositoryAddedAction sending RepositoryAdded Event for repo %s", *repo.FullName)
	s.eventService.LogEvent(&events.LogEventArgs{
		EventType: events.RepositoryAdded,
		ProjectID: repoModel.RepositoryProjectID,
		UserID:    *sender.Login,
		EventData: &events.RepositoryAddedEventData{
			RepositoryName: *repo.FullName,
		},
	})

	return nil
}

func (s *eventHandlerService) handleRepositoryRemovedAction(sender *github.User, repo *github.Repository) error {
	if repo.ID == nil || *repo.ID == 0 {
		return fmt.Errorf("missing repo id")
	}
	repositoryExternalID := strconv.FormatInt(*repo.ID, 10)
	repoModel, err := s.githubRepo.GetRepositoryByGithubID(context.Background(), repositoryExternalID, true)
	if err != nil {
		if errors.Is(err, repositories.ErrGithubRepositoryNotFound) {
			log.Warnf("event for non existing local repo : %s, nothing to do", *repo.FullName)
			return nil
		}
		return fmt.Errorf("fetching the repo : %s by external id : %s failed : %v", *repo.FullName, repositoryExternalID, err)
	}

	if err := s.githubRepo.DisableRepository(context.Background(), repoModel.RepositoryID); err != nil {
		log.Warnf("disabling repo : %s failed : %v", *repo.FullName, err)
		return err
	}

	// sending event for the action
	s.eventService.LogEvent(&events.LogEventArgs{
		EventType: events.RepositoryDisabled,
		ProjectID: repoModel.RepositoryProjectID,
		UserID:    *sender.Login,
		EventData: &events.RepositoryDisabledEventData{
			RepositoryName: *repo.FullName,
		},
	})

	return nil
}

func (s *eventHandlerService) ProcessInstallationRepositoriesEvent(event *github.InstallationRepositoriesEvent) error {
	log.Debugf("ProcessInstallationRepositoriesEvent called for action : %s", *event.Action)
	if event.Action == nil {
		return fmt.Errorf("no action found in event payload")
	}
	switch *event.Action {
	case "added":
		if len(event.RepositoriesAdded) == 0 {
			log.Warnf("repositories list is empty nothing to add")
			return nil
		}

		for _, r := range event.RepositoriesAdded {
			if err := s.handleRepositoryAddedAction(event.Sender, r); err != nil {
				// we just log it don't want to stop the whole process at this stage
				log.Warnf("adding the repository : %s failed : %v", *r.FullName, err)
			}
		}
	case "removed":
		if len(event.RepositoriesRemoved) == 0 {
			log.Warnf("repositories list is empty nothing to remove")
			return nil
		}
		for _, r := range event.RepositoriesRemoved {
			if err := s.handleRepositoryRemovedAction(event.Sender, r); err != nil {
				log.Warnf("removing the repository : %s failed : %v", *r.FullName, err)
			}
		}
	default:
		log.Warnf("ProcessInstallationRepositoriesEvent no handler for action : %s", *event.Action)
	}

	return nil
}

func (s *eventHandlerService) handlePullRequestComment(event *github.IssueCommentEvent) error {
	if event.Comment == nil {
		log.Warnf("comment object missing")
		return nil
	}
	comment := utils.GetString(event.Comment.Body)
	if comment == "" {
		log.Warnf("empty comment body nothing to process")
		return nil
	}

	if !strings.Contains(comment, "/easycla") {
		log.Warnf("non recognized comment command, nothing to process : %s", comment)
		return nil
	}

	if event.Installation == nil || event.Installation.GetID() == 0 {
		log.Warnf("installation id missing can't proceed")
		return nil
	}
	installationID := *event.Installation.ID

	if event.Repo == nil || event.Repo.GetID() == 0 {
		log.Warnf("missing github repo id can't proceed")
		return nil
	}
	githubRepoID := event.Repo.GetID()

	if event.Issue == nil || event.Issue.GetID() == 0 {
		log.Warnf("missing pull request id ")
		return nil
	}
	pullRequestID := event.Issue.GetID()

	return s.updatePullRequest(installationID, githubRepoID, pullRequestID)
}

func (s *eventHandlerService) updatePullRequest(installationID int64, githubRepoID, pullRequestID int64) error {
	ctx := context.Background()
	pullRequest, err := githubutils.GetPullRequest(ctx, installationID, githubRepoID, pullRequestID)
	if err != nil {
		return err
	}

	githubRepo, err := githubutils.GetRepositoryByExternalID(ctx, installationID, githubRepoID)
	if err != nil {
		return err
	}

	commitAuthors, err := githubutils.GetPullRequestCommitAuthors(ctx, installationID, githubRepo, pullRequest)
	if err != nil {
		return fmt.Errorf("fetching commitAuthors failed for repo : %s in pull request : %d : %v", githubRepo.GetName(), pullRequest.GetID(), err)
	}

	if len(commitAuthors) == 0 {
		return fmt.Errorf("no commitAuthors found for repo : %s in pull request : %d", githubRepo.GetName(), pullRequest.GetID())
	}

	repo, err := s.githubRepo.GetRepositoryByGithubID(ctx, strconv.Itoa(int(githubRepo.GetID())), true)
	if err != nil {
		log.Warnf("fetching github repo : %s from db failed : %v", githubRepoID, err)
		return err
	}

	orgName := repo.RepositoryOrganizationName
	log.Debugf("PR: %d, determined github organization is: %s", pullRequest.GetID(), orgName)

	githubOrg, err := s.githubOrgRepo.GetGithubOrganization(ctx, orgName)
	if err != nil {
		return fmt.Errorf("fetching github org : %s failed : %w", orgName, err)
	}

	if githubOrg.OrganizationInstallationID != installationID {
		return fmt.Errorf("installation id mismatch githubOrg has : %d, pullRequest got : %d", githubOrg.OrganizationInstallationID, installationID)
	}

	for _, commitAuthor := range commitAuthors {
		log.Debugf("processing commit author : %s", commitAuthor.AuthorName)
	}

	return nil
}
