// Copyright The Linux Foundation and each contributor to CommunityBridge.
// SPDX-License-Identifier: MIT

package github

import (
	"context"
	"errors"
	"fmt"

	"github.com/communitybridge/easycla/cla-backend-go/utils"
	"github.com/sirupsen/logrus"
	log "github.com/sirupsen/logrus"

	"github.com/communitybridge/easycla/cla-backend-go/logging"
	"github.com/google/go-github/v32/github"
)

// errors
var (
	ErrGithubRepositoryNotFound = errors.New("github repository not found")
)

type PullRequestCommitAuthor struct {
	CommitSha   string
	AuthorID    int64
	AuthorName  string
	AuthorEmail string
}

// GetPullRequestCommitAuthors extracts the pull authors from the given pull request
func GetPullRequestCommitAuthors(ctx context.Context, installationID int64, githubRepo *github.Repository, pullRequest *github.PullRequest) ([]*PullRequestCommitAuthor, error) {
	client, err := NewGithubAppClient(installationID)
	if err != nil {
		return nil, err
	}

	commits, _, err := client.PullRequests.ListCommits(ctx, githubRepo.Owner.GetLogin(), githubRepo.GetName(), int(*pullRequest.ID), nil)
	if err != nil {
		logging.Warnf("fetching commits for pull request : %d failed : %v", *pullRequest.ID, err)
		return nil, err
	}

	var pullRequestCommitAuthors []*PullRequestCommitAuthor
	for _, commit := range commits {
		if commit.Commit.Author == nil || commit.Author == nil {
			log.Warnf("pr : %d commit %s doesn't have any author skipping", *pullRequest.ID, commit.GetSHA())
			continue
		}

		pullRequestCommitAuthor := &PullRequestCommitAuthor{
			CommitSha: commit.GetSHA(),
		}
		if commit.Author != nil {
			if commit.Author.GetLogin() != "" {
				pullRequestCommitAuthor.AuthorName = commit.Author.GetLogin()
			}

			if commit.Author.GetID() != 0 {
				pullRequestCommitAuthor.AuthorID = commit.Author.GetID()
			}

			if commit.Author.GetEmail() != "" {
				pullRequestCommitAuthor.AuthorEmail = commit.Author.GetEmail()
			}
		}

		if commit.Commit.Author != nil {
			commitAuthor := commit.Commit.Author
			if pullRequestCommitAuthor.AuthorName == "" {
				if commitAuthor.GetName() != "" {
					pullRequestCommitAuthor.AuthorName = commitAuthor.GetName()
				} else if commitAuthor.GetLogin() != "" {
					pullRequestCommitAuthor.AuthorName = commitAuthor.GetLogin()
				}
			}

			if pullRequestCommitAuthor.AuthorEmail == "" && commitAuthor.GetEmail() != "" {
				pullRequestCommitAuthor.AuthorEmail = commitAuthor.GetEmail()
			}
		}
		pullRequestCommitAuthors = append(pullRequestCommitAuthors, pullRequestCommitAuthor)
	}
	return pullRequestCommitAuthors, nil
}

// GetPullRequest fetches the github pull request
func GetPullRequest(ctx context.Context, installationID, githubRepoID, pullRequestID int64) (*github.PullRequest, error) {
	repo, err := GetRepositoryByExternalID(ctx, installationID, githubRepoID)
	if err != nil {
		return nil, err
	}

	client, err := NewGithubAppClient(installationID)
	if err != nil {
		return nil, err
	}

	owner := repo.Owner.GetLogin()
	if owner == "" {
		return nil, fmt.Errorf("missing owner in repo response")
	}

	pullRequest, _, err := client.PullRequests.Get(ctx, *repo.Owner.Login, repo.GetName(), int(pullRequestID))
	if err != nil {
		log.Warnf("fetching pull request : %d for repo : %s failed : %v", pullRequestID, repo.GetName(), err)
		return nil, err
	}

	return pullRequest, nil
}

// GetRepositoryByExternalID finds github repository by github repository id
func GetRepositoryByExternalID(ctx context.Context, installationID, id int64) (*github.Repository, error) {
	client, err := NewGithubAppClient(installationID)
	if err != nil {
		return nil, err
	}
	org, resp, err := client.Repositories.GetByID(ctx, id)
	if err != nil {
		logging.Warnf("GetRepository %v failed. error = %s", id, err.Error())
		if resp.StatusCode == 404 {
			return nil, ErrGithubRepositoryNotFound
		}
		return nil, err
	}
	return org, nil
}

// GetRepositories gets github repositories by organization
func GetRepositories(ctx context.Context, organizationName string) ([]*github.Repository, error) {
	f := logrus.Fields{
		"functionName":     "GetRepositories",
		utils.XREQUESTID:   ctx.Value(utils.XREQUESTID),
		"organizationName": organizationName,
	}

	// Get the client with token
	client := NewGithubOauthClient()

	var responseRepoList []*github.Repository
	var nextPage = 1
	for {
		// API https://docs.github.com/en/free-pro-team@latest/rest/reference/repos
		// API Pagination: https://docs.github.com/en/free-pro-team@latest/rest/guides/traversing-with-pagination
		repoList, resp, err := client.Repositories.ListByOrg(ctx, organizationName, &github.RepositoryListByOrgOptions{
			Type:      "public",
			Sort:      "full_name",
			Direction: "asc",
			ListOptions: github.ListOptions{
				Page:    nextPage,
				PerPage: 100,
			},
		})
		if err != nil {
			log.WithFields(f).WithError(err).Warn("unable to list repositories for organization")
			if resp != nil && resp.StatusCode == 404 {
				return nil, ErrGithubOrganizationNotFound
			}
			return nil, err
		}

		if resp.StatusCode < 200 || resp.StatusCode > 299 {
			msg := fmt.Sprintf("GetRepositories %s failed with no success response code %d. error = %s", organizationName, resp.StatusCode, err.Error())
			log.WithFields(f).Warnf(msg)
			return nil, errors.New(msg)
		}

		// Append our results to the response...
		responseRepoList = append(responseRepoList, repoList...)
		// if no more pages...
		if resp.NextPage == 0 {
			break
		}

		// update our next page value
		nextPage = resp.NextPage
	}

	return responseRepoList, nil
}
