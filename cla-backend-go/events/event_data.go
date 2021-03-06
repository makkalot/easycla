//nolint
package events

import (
	"fmt"
)

// EventData returns event data string which is used for event logging and containsPII field
type EventData interface {
	GetEventString(args *LogEventArgs) (eventData string, containsPII bool)
}

type GithubRepositoryAddedEventData struct {
	RepositoryName string
}
type GithubRepositoryDeletedEventData struct {
	RepositoryName string
}

type GerritProjectDeletedEventData struct {
	DeletedCount int
}

type GerritAddedEventData struct {
	GerritRepositoryName string
}

type GerritDeletedEventData struct {
	GerritRepositoryName string
}

type GithubProjectDeletedEventData struct {
	DeletedCount int
}

type SignatureProjectInvalidatedEventData struct {
	InvalidatedCount int
}

type UserCreatedEventData struct{}
type UserDeletedEventData struct {
	DeletedUserID string
}
type UserUpdatedEventData struct{}

type CompanyACLRequestAddedEventData struct {
	UserName  string
	UserID    string
	UserEmail string
}

type CompanyACLRequestApprovedEventData struct {
	UserName  string
	UserID    string
	UserEmail string
}

type CompanyACLRequestDeniedEventData struct {
	UserName  string
	UserID    string
	UserEmail string
}

type CompanyACLUserAddedEventData struct {
	UserLFID string
}

type CLATemplateCreatedEventData struct{}

type GithubOrganizationAddedEventData struct {
	GithubOrganizationName string
}

type GithubOrganizationDeletedEventData struct {
	GithubOrganizationName string
}

type CCLAApprovalListRequestCreatedEventData struct {
	RequestID string
}

type CCLAApprovalListRequestApprovedEventData struct {
	RequestID string
}

type CCLAApprovalListRequestRejectedEventData struct {
	RequestID string
}

type CLAManagerCreatedEventData struct {
	CompanyName string
	ProjectName string
	UserName    string
	UserEmail   string
	UserLFID    string
}

type CLAManagerDeletedEventData struct {
	CompanyName string
	ProjectName string
	UserName    string
	UserEmail   string
	UserLFID    string
}

type CLAManagerRequestCreatedEventData struct {
	RequestID   string
	CompanyName string
	ProjectName string
	UserName    string
	UserEmail   string
	UserLFID    string
}

type CLAManagerRequestApprovedEventData struct {
	RequestID    string
	CompanyName  string
	ProjectName  string
	UserName     string
	UserEmail    string
	ManagerName  string
	ManagerEmail string
}

type CLAManagerRequestDeniedEventData struct {
	RequestID    string
	CompanyName  string
	ProjectName  string
	UserName     string
	UserEmail    string
	ManagerName  string
	ManagerEmail string
}

type CLAManagerRequestDeletedEventData struct {
	RequestID    string
	CompanyName  string
	ProjectName  string
	UserName     string
	UserEmail    string
	ManagerName  string
	ManagerEmail string
}

type CLAApprovalListAddEmailData struct {
	UserName          string
	UserEmail         string
	UserLFID          string
	ApprovalListEmail string
}

type CLAApprovalListRemoveEmailData struct {
	UserName          string
	UserEmail         string
	UserLFID          string
	ApprovalListEmail string
}

type CLAApprovalListAddDomainData struct {
	UserName           string
	UserEmail          string
	UserLFID           string
	ApprovalListDomain string
}

type CLAApprovalListRemoveDomainData struct {
	UserName           string
	UserEmail          string
	UserLFID           string
	ApprovalListDomain string
}

type CLAApprovalListAddGitHubUsernameData struct {
	UserName                   string
	UserEmail                  string
	UserLFID                   string
	ApprovalListGitHubUsername string
}

type CLAApprovalListRemoveGitHubUsernameData struct {
	UserName                   string
	UserEmail                  string
	UserLFID                   string
	ApprovalListGitHubUsername string
}

type CLAApprovalListAddGitHubOrgData struct {
	UserName              string
	UserEmail             string
	UserLFID              string
	ApprovalListGitHubOrg string
}

type CLAApprovalListRemoveGitHubOrgData struct {
	UserName              string
	UserEmail             string
	UserLFID              string
	ApprovalListGitHubOrg string
}

type ApprovalListGithubOrganizationAddedEventData struct {
	GithubOrganizationName string
}
type ApprovalListGithubOrganizationDeletedEventData struct {
	GithubOrganizationName string
}
type ClaManagerAccessRequestAddedEventData struct {
	ProjectName string
	CompanyName string
}
type ClaManagerAccessRequestDeletedEventData struct {
	RequestID string
}

type CLAGroupCreatedEventData struct{}
type CLAGroupUpdatedEventData struct{}
type CLAGroupDeletedEventData struct{}

type ContributorNotifyCompanyAdminData struct {
	AdminName  string
	AdminEmail string
}

type ContributorNotifyCLADesignee struct {
	DesigneeName  string
	DesigneeEmail string
}

type ContributorAssignCLADesignee struct {
	DesigneeName  string
	DesigneeEmail string
}

type UserConvertToContactData struct{}

type AssignRoleScopeData struct {
	Role  string
	Scope string
}

type ClaManagerRoleCreatedData struct {
	Role      string
	Scope     string
	UserName  string
	UserEmail string
}

type ClaManagerRoleDeletedData struct {
	Role      string
	Scope     string
	UserName  string
	UserEmail string
}

func (ed *GithubRepositoryAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added github repository [%s] to project [%s]", args.userName, ed.RepositoryName, args.projectName)
	return data, true
}

func (ed *GithubRepositoryDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] deleted github repository [%s] from project [%s]", args.userName, ed.RepositoryName, args.projectName)
	return data, true
}

func (ed *UserCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added. user details = [%+v]", args.userName, args.UserModel)
	return data, true
}

func (ed *UserUpdatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	return fmt.Sprintf("user [%s] updated. user details = [%+v]", args.userName, *args.UserModel), true
}

func (ed *UserDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] deleted user id: [%s]", args.userName, ed.DeletedUserID)
	return data, true
}

func (ed *CompanyACLRequestAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added pending invite with id [%s], email [%s] for company: [%s]",
		ed.UserName, ed.UserID, ed.UserEmail, args.companyName)
	return data, true
}

func (ed *CompanyACLRequestApprovedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] company invite was approved access with id [%s], email [%s] for company: [%s]",
		ed.UserName, ed.UserID, ed.UserEmail, args.companyName)
	return data, true
}

func (ed *CompanyACLRequestDeniedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] company invite was denied access with id [%s], email [%s] for company: [%s]",
		ed.UserName, ed.UserID, ed.UserEmail, args.companyName)
	return data, true
}

func (ed *CompanyACLUserAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added user with lf username [%s] to the ACL for company: [%s]",
		args.userName, ed.UserLFID, args.companyName)
	return data, true
}

func (ed *CLATemplateCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] created PDF templates for project [%s]", args.userName, args.projectName)
	return data, true
}

func (ed *GithubOrganizationAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added github organization [%s]",
		args.userName, ed.GithubOrganizationName)
	return data, true
}

func (ed *GithubOrganizationDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] deleted github organization [%s]",
		args.userName, ed.GithubOrganizationName)
	return data, true
}

func (ed *CCLAApprovalListRequestApprovedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] approved a CCLA Approval Request for project: [%s], company: [%s] - request id: %s",
		args.userName, args.projectName, args.companyName, ed.RequestID)
	return data, true
}

func (ed *CCLAApprovalListRequestRejectedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] rejected a CCLA Approval Request for project: [%s], company: [%s] - request id: %s",
		args.userName, args.projectName, args.companyName, ed.RequestID)
	return data, true
}

func (ed *CLAManagerRequestCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s / %s / %s] added CLA Manager Request [%s] for Company: %s, Project: %s",
		ed.UserLFID, ed.UserName, ed.UserEmail, ed.RequestID, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAManagerCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s / %s / %s] was added as CLA Manager for Company: %s, Project: %s",
		ed.UserLFID, ed.UserName, ed.UserEmail, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAManagerDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s / %s / %s] was removed as CLA Manager for Company: %s, Project: %s",
		ed.UserLFID, ed.UserName, ed.UserEmail, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAManagerRequestApprovedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager Request [%s] for user [%s / %s] was approved by [%s / %s] for Company: %s, Project: %s",
		ed.RequestID, ed.UserName, ed.UserEmail, ed.ManagerName, ed.ManagerEmail, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAManagerRequestDeniedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager Request [%s] for user [%s / %s] was denied by [%s / %s] for Company: %s, Project: %s",
		ed.RequestID, ed.UserName, ed.UserEmail, ed.ManagerName, ed.ManagerEmail, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAManagerRequestDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager Request [%s] for user [%s / %s] was deleted by [%s / %s] for Company: %s, Project: %s",
		ed.RequestID, ed.UserName, ed.UserEmail, ed.ManagerName, ed.ManagerEmail, ed.CompanyName, ed.ProjectName)
	return data, true
}

func (ed *CLAApprovalListAddEmailData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] added Email %s to the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListEmail, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListRemoveEmailData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] removed Email %s from the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListEmail, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListAddDomainData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] added Domain %s to the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListDomain, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListRemoveDomainData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] removed Domain %s from the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListDomain, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListAddGitHubUsernameData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] added GitHub Username %s to the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListGitHubUsername, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListRemoveGitHubUsernameData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] removed GitHub Username %s from the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListGitHubUsername, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListAddGitHubOrgData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] added GitHub Org %s to the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListGitHubOrg, args.companyName, args.projectName)
	return data, true
}

func (ed *CLAApprovalListRemoveGitHubOrgData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s / %s / %s] removed GitHub Org %s from the approval list for Company: %s, Project: %s",
		ed.UserName, ed.UserEmail, ed.UserLFID, ed.ApprovalListGitHubOrg, args.companyName, args.projectName)
	return data, true
}

func (ed *CCLAApprovalListRequestCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] created a CCLA Approval Request for project: [%s], company: [%s] - request id: %s",
		args.userName, args.projectName, args.companyName, ed.RequestID)
	return data, true
}

func (ed *ApprovalListGithubOrganizationAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s] added GitHub Organization [%s] to the whitelist for project [%s] company [%s]",
		args.userName, ed.GithubOrganizationName, args.projectName, args.companyName)
	return data, true
}

func (ed *ApprovalListGithubOrganizationDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("CLA Manager [%s] removed GitHub Organization [%s] from the whitelist for project [%s] company [%s]",
		args.userName, ed.GithubOrganizationName, args.projectName, args.companyName)
	return data, true
}

func (ed *ClaManagerAccessRequestAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has requested to be cla manager for project [%s] company [%s]",
		args.userName, ed.ProjectName, ed.CompanyName)
	return data, true
}

func (ed *ClaManagerAccessRequestDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has deleted request with id [%s] to be cla manager",
		args.userName, ed.RequestID)
	return data, true
}

func (ed *CLAGroupCreatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has created a CLA Group [%s - %s]",
		args.userName, args.projectName, args.ProjectID)
	return data, true
}

func (ed *CLAGroupUpdatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has updated CLA Group [%s - %s]",
		args.userName, args.projectName, args.ProjectID)
	return data, true
}
func (ed *CLAGroupDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has deleted CLA Group [%s - %s]",
		args.userName, args.projectName, args.ProjectID)
	return data, true
}

func (ed *GerritProjectDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("Deleted %d Gerrit Repositories due to CLA Group/Project: [%s] deletion",
		ed.DeletedCount, args.projectName)
	containsPII := false
	return data, containsPII
}

func (ed *GerritAddedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has added gerrit [%s]", args.userName, ed.GerritRepositoryName)
	containsPII := true
	return data, containsPII
}

func (ed *GerritDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] has deleted gerrit [%s]", args.userName, ed.GerritRepositoryName)
	containsPII := true
	return data, containsPII
}

func (ed *GithubProjectDeletedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("Deleted %d Github Repositories  due to CLA Group/Project: [%s] deletion",
		ed.DeletedCount, args.projectName)
	return data, true
}

func (ed *SignatureProjectInvalidatedEventData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("Invalidated %d signatures (approved set to false) due to CLA Group/Project: [%s] deletion",
		ed.InvalidatedCount, args.projectName)
	return data, true
}

func (ed *ContributorNotifyCompanyAdminData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] notified company admin by email: %s %s for company [%s / %s]",
		args.userName, ed.AdminName, ed.AdminEmail, args.companyName, args.CompanyID)
	return data, true
}

func (ed *ContributorNotifyCLADesignee) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] notified CLA Designee by email: %s %s for project [%s / %s] company [%s / %s]",
		args.userName, ed.DesigneeName, ed.DesigneeEmail,
		args.projectName, args.ExternalProjectID,
		args.companyName, args.CompanyID)
	return data, true
}

func (ed *ContributorAssignCLADesignee) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] assigned user: [%s / %s] as CLA Manager Designee for project [%s / %s] company [%s / %s]",
		args.userName, ed.DesigneeName, ed.DesigneeEmail,
		args.projectName, args.ExternalProjectID,
		args.companyName, args.CompanyID)
	return data, true
}

func (ed *UserConvertToContactData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] converted to Contact state for project [%s]",
		args.LfUsername, args.ExternalProjectID)
	return data, true
}

func (ed *AssignRoleScopeData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] assigned scope [%s] with role [%s] for project [%s]",
		args.LfUsername,
		ed.Scope, ed.Role, args.ExternalProjectID)
	return data, true
}

func (ed *ClaManagerRoleCreatedData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] added user %s/%s from role: %s with scope: %s", args.userName, ed.UserName, ed.UserEmail, ed.Role, ed.Scope)
	return data, false
}

func (ed *ClaManagerRoleDeletedData) GetEventString(args *LogEventArgs) (string, bool) {
	data := fmt.Sprintf("user [%s] removed user %s/%s from role: %s with scope: %s", args.userName, ed.UserName, ed.UserEmail, ed.Role, ed.Scope)
	return data, false
}
