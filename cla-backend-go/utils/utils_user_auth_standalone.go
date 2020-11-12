// +build !aws_lambda

// Copyright The Linux Foundation and each contributor to CommunityBridge.
// SPDX-License-Identifier: MIT

package utils

import (
	"os"
	"strconv"

	"github.com/LF-Engineering/lfx-kit/auth"
	log "github.com/communitybridge/easycla/cla-backend-go/logging"
)

// IsUserAdmin helper function for determining if the user is an admin
func IsUserAdmin(user *auth.User) bool {
	return user.Admin
}

// skipPermissionChecks determines if we can skip the permissions checks when running locally (for testing)
func skipPermissionChecks() bool {
	environmentKey := "DISABLE_LOCAL_PERMISSION_CHECKS"
	disablePermissionChecks, err := strconv.ParseBool(os.Getenv(environmentKey))
	if err != nil {
		log.Warnf("unable to check local permissions flag: %t", disablePermissionChecks)
		return false
	}

	if disablePermissionChecks {
		log.Debugf("skipping permission checks since %s is set to true", environmentKey)
	}

	return disablePermissionChecks
}

// IsUserAuthorizedForOrganization helper function for determining if the user is authorized for this company
func IsUserAuthorizedForOrganization(user *auth.User, companySFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	// Previously, we checked for user.Admin - admins should be in a separate role
	// Previously, we checked for user.Allowed, which is currently not used (future flag that is currently not implemented)
	return user.IsUserAuthorizedForOrganizationScope(companySFID)
}

// IsUserAuthorizedForProjectTree helper function for determining if the user is authorized for this project hierarchy/tree
func IsUserAuthorizedForProjectTree(user *auth.User, projectSFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	// Previously, we checked for user.Admin - admins should be in a separate role
	// Previously, we checked for user.Allowed, which is currently not used (future flag that is currently not implemented)
	return user.IsUserAuthorized(auth.Project, projectSFID, true)
}

// IsUserAuthorizedForProject helper function for determining if the user is authorized for this project
func IsUserAuthorizedForProject(user *auth.User, projectSFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	// Previously, we checked for user.Admin - admins should be in a separate role
	// Previously, we checked for user.Allowed, which is currently not used (future flag that is currently not implemented)
	return user.IsUserAuthorizedForProjectScope(projectSFID)
}

// IsUserAuthorizedForAnyProjects helper function for determining if the user is authorized for any of the specified projects
func IsUserAuthorizedForAnyProjects(user *auth.User, projectSFIDs []string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	for _, projectSFID := range projectSFIDs {
		if IsUserAuthorizedForProjectTree(user, projectSFID) {
			return true
		}
		if IsUserAuthorizedForProject(user, projectSFID) {
			return true
		}
	}

	return false
}

// IsUserAuthorizedForProjectOrganization helper function for determining if the user is authorized for this project organization scope
func IsUserAuthorizedForProjectOrganization(user *auth.User, projectSFID, companySFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	// Previously, we checked for user.Allowed, which is currently not used (future flag that is currently not implemented)
	return user.IsUserAuthorizedByProject(projectSFID, companySFID)
}

// IsUserAuthorizedForAnyProjectOrganization helper function for determining if the user is authorized for any of the specified projects with scope of project + organization
func IsUserAuthorizedForAnyProjectOrganization(user *auth.User, projectSFIDs []string, companySFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	for _, projectSFID := range projectSFIDs {
		if IsUserAuthorizedForProjectOrganizationTree(user, projectSFID, companySFID) {
			return true
		}
		if IsUserAuthorizedForProjectOrganization(user, projectSFID, companySFID) {
			return true
		}
	}

	return false
}

// IsUserAuthorizedForProjectOrganizationTree helper function for determining if the user is authorized for this project organization scope and nested projects/orgs
func IsUserAuthorizedForProjectOrganizationTree(user *auth.User, projectSFID, companySFID string) bool {
	// If we are running locally and want to disable permission checks
	if skipPermissionChecks() {
		return true
	}

	// Previously, we checked for user.Admin - admins should be in a separate role
	// Previously, we checked for user.Allowed, which is currently not used (future flag that is currently not implemented)
	return user.IsUserAuthorized(auth.ProjectOrganization, projectSFID+"|"+companySFID, true)
}
