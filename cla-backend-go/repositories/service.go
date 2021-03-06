// Copyright The Linux Foundation and each contributor to CommunityBridge.
// SPDX-License-Identifier: MIT

package repositories

import (
	"github.com/communitybridge/easycla/cla-backend-go/gen/models"
	log "github.com/communitybridge/easycla/cla-backend-go/logging"
)

// Service contains functions of Github Repository service
type Service interface {
	AddGithubRepository(externalProjectID string, input *models.GithubRepositoryInput) (*models.GithubRepository, error)
	DeleteGithubRepository(externalProjectID string, repositoryID string) error
	ListProjectRepositories(externalProjectID string) (*models.ListGithubRepositories, error)
	GetGithubRepository(repositoryID string) (*models.GithubRepository, error)
	DeleteProject(projectID string) (int, error)
	GetGithubRepositoryByCLAGroup(claGroupID string) (*models.GithubRepository, error)
}

type service struct {
	repo Repository
	//projectRepository project.Repository
}

// NewService creates a new githubOrganizations service
func NewService(repo Repository) Service {
	return &service{
		repo: repo,
		//projectRepository: projectRepository,
	}
}

func (s *service) AddGithubRepository(externalProjectID string, input *models.GithubRepositoryInput) (*models.GithubRepository, error) {
	projectSFID := externalProjectID
	return s.repo.AddGithubRepository(externalProjectID, projectSFID, input)
}
func (s *service) DeleteGithubRepository(externalProjectID string, repositoryID string) error {
	return s.repo.DeleteGithubRepository(externalProjectID, "", repositoryID)
}
func (s *service) ListProjectRepositories(externalProjectID string) (*models.ListGithubRepositories, error) {
	return s.repo.ListProjectRepositories(externalProjectID, "")
}
func (s *service) GetGithubRepository(repositoryID string) (*models.GithubRepository, error) {
	return s.repo.GetGithubRepository(repositoryID)
}

// DeleteProject removes the repositories by Organizations
func (s *service) DeleteProject(projectID string) (int, error) {
	var deleteErr error
	ghOrgs, err := s.repo.GetProjectRepositoriesGroupByOrgs(projectID)
	if err != nil {
		return 0, err
	}
	if len(ghOrgs) > 0 {
		log.Debugf("Deleting repositories for project :%s", projectID)
		for _, ghOrg := range ghOrgs {
			for _, item := range ghOrg.List {
				deleteErr = s.repo.DeleteProject(item.RepositoryID)
				if deleteErr != nil {
					log.Warnf("Unable to remove repository: %s for project :%s error :%v", item.RepositoryID, projectID, deleteErr)
				}
			}
		}
	}

	return len(ghOrgs), nil
}

func (s *service) GetGithubRepositoryByCLAGroup(claGroupID string) (*models.GithubRepository, error) {
	return s.repo.GetGithubRepositoryByCLAGroup(claGroupID)
}
