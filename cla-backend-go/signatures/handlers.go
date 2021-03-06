// Copyright The Linux Foundation and each contributor to CommunityBridge.
// SPDX-License-Identifier: MIT

package signatures

import (
	"fmt"
	"net/http"

	"github.com/communitybridge/easycla/cla-backend-go/events"
	"github.com/communitybridge/easycla/cla-backend-go/gen/models"
	"github.com/communitybridge/easycla/cla-backend-go/gen/restapi/operations"
	"github.com/communitybridge/easycla/cla-backend-go/gen/restapi/operations/signatures"
	"github.com/communitybridge/easycla/cla-backend-go/github"
	log "github.com/communitybridge/easycla/cla-backend-go/logging"
	"github.com/communitybridge/easycla/cla-backend-go/user"
	"github.com/communitybridge/easycla/cla-backend-go/utils"
	"github.com/go-openapi/runtime"
	"github.com/go-openapi/runtime/middleware"
	"github.com/savaki/dynastore"
)

// Configure setups handlers on api with service
func Configure(api *operations.ClaAPI, service SignatureService, sessionStore *dynastore.Store, eventsService events.Service) { // nolint

	api.SignaturesGetSignedICLADocumentHandler = signatures.GetSignedICLADocumentHandlerFunc(func(params signatures.GetSignedICLADocumentParams) middleware.Responder {
		signatureModel, sigErr := service.GetIndividualSignature(params.ClaGroupID, params.UserID)
		if sigErr != nil {
			msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error -  error retrieving signature using ClaGroupID: %s, userID: %s, error: %+v",
				params.ClaGroupID, params.UserID, sigErr)
			log.Warn(msg)
			return signatures.NewGetSignedICLADocumentInternalServerError().WithPayload(&models.ErrorResponse{
				Code:    "500",
				Message: msg,
			})
		}

		if signatureModel == nil {
			msg := fmt.Sprintf("EasyCLA - 404 Not Found - -  error retrieving signature using claGroupID: %s, userID: %s",
				params.ClaGroupID, params.UserID)
			log.Warn(msg)
			return signatures.NewGetSignedICLADocumentNotFound().WithPayload(&models.ErrorResponse{
				Code:    "404",
				Message: msg,
			})
		}

		downloadURL := fmt.Sprintf("contract-group/%s/icla/%s/%s.pdf",
			params.ClaGroupID, params.UserID, signatureModel.SignatureID)
		log.Debugf("Retrieving PDF from path: %s", downloadURL)
		downloadLink, s3Err := utils.GetDownloadLink(downloadURL)
		if s3Err != nil {
			msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error -  unable to locate PDF from source using ClaGroupID: %s, userID: %s, s3 error: %+v",
				params.ClaGroupID, params.UserID, s3Err)
			log.Warn(msg)
			return signatures.NewGetSignedICLADocumentInternalServerError().WithPayload(&models.ErrorResponse{
				Code:    "500",
				Message: msg,
			})
		}

		return middleware.ResponderFunc(func(rw http.ResponseWriter, p runtime.Producer) {
			rw.Header().Set("Content-type", "text/html")
			rw.WriteHeader(200)
			redirectDocument := generateHTMLRedirectPage(downloadLink, "ICLA")
			bytesWritten, writeErr := rw.Write([]byte(redirectDocument))
			if writeErr != nil {
				msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error - generating s3 redirect for the client client using source using claGroupID: %s, userID: %s, error: %+v",
					params.ClaGroupID, params.UserID, s3Err)
				log.Warn(msg)
			}
			log.Debugf("SignaturesGetSignedICLADocumentHandler - wrote %d bytes", bytesWritten)
		})
	})

	api.SignaturesGetSignedCCLADocumentHandler = signatures.GetSignedCCLADocumentHandlerFunc(func(params signatures.GetSignedCCLADocumentParams) middleware.Responder {
		signatureModel, sigErr := service.GetCorporateSignature(params.ClaGroupID, params.CompanyID)
		if sigErr != nil {
			msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error -  error retrieving signature using ClaGroupID: %s, CompanyID: %s, error: %+v",
				params.ClaGroupID, params.CompanyID, sigErr)
			log.Warn(msg)
			return signatures.NewGetSignedCCLADocumentInternalServerError().WithPayload(&models.ErrorResponse{
				Code:    "500",
				Message: msg,
			})

		}

		if signatureModel == nil {
			msg := fmt.Sprintf("EasyCLA - 404 Not Found - -  error retrieving signature using ClaGroupID: %s, CompanyID: %s",
				params.ClaGroupID, params.CompanyID)
			log.Warn(msg)
			return signatures.NewGetSignedCCLADocumentNotFound().WithPayload(&models.ErrorResponse{
				Code:    "404",
				Message: msg,
			})
		}

		downloadURL := fmt.Sprintf("contract-group/%s/ccla/%s/%s.pdf",
			params.ClaGroupID, params.CompanyID, signatureModel.SignatureID)
		log.Debugf("Retrieving PDF from path: %s", downloadURL)
		downloadLink, s3Err := utils.GetDownloadLink(downloadURL)
		if s3Err != nil {
			msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error -  unable to locate PDF from source using ClaGroupID: %s, CompanyID: %s, s3 error: %+v",
				params.ClaGroupID, params.CompanyID, s3Err)
			log.Warn(msg)
			return signatures.NewGetSignedCCLADocumentInternalServerError().WithPayload(&models.ErrorResponse{
				Code:    "500",
				Message: msg,
			})
		}

		return middleware.ResponderFunc(func(rw http.ResponseWriter, p runtime.Producer) {
			rw.Header().Set("Content-type", "text/html")
			rw.WriteHeader(200)
			redirectDocument := generateHTMLRedirectPage(downloadLink, "CCLA")
			bytesWritten, writeErr := rw.Write([]byte(redirectDocument))
			if writeErr != nil {
				msg := fmt.Sprintf("EasyCLA - 500 Internal Server Error - generating s3 redirect for the client client using source using ClaGroupID: %s, CompanyID: %s, error: %+v",
					params.ClaGroupID, params.CompanyID, s3Err)
				log.Warn(msg)
			}
			log.Debugf("SignaturesGetSignedICLADocumentHandler - wrote %d bytes", bytesWritten)
		})
	})

	// Get Signature
	api.SignaturesGetSignatureHandler = signatures.GetSignatureHandlerFunc(func(params signatures.GetSignatureParams, claUser *user.CLAUser) middleware.Responder {

		signature, err := service.GetSignature(params.SignatureID)
		if err != nil {
			log.Warnf("error retrieving signature metrics, error: %+v", err)
			return signatures.NewGetSignatureBadRequest().WithPayload(errorResponse(err))
		}

		if signature == nil {
			return signatures.NewGetSignatureNotFound()
		}

		return signatures.NewGetSignatureOK().WithPayload(signature)
	})

	// Retrieve GitHub Approval List Entries
	api.SignaturesGetGitHubOrgWhitelistHandler = signatures.GetGitHubOrgWhitelistHandlerFunc(func(params signatures.GetGitHubOrgWhitelistParams, claUser *user.CLAUser) middleware.Responder {
		session, err := sessionStore.Get(params.HTTPRequest, github.SessionStoreKey)
		if err != nil {
			log.Warnf("error retrieving session from the session store, error: %+v", err)
			return signatures.NewGetGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		githubAccessToken, ok := session.Values["github_access_token"].(string)
		if !ok {
			log.Debugf("no github access token in the session - initializing to empty string")
			githubAccessToken = ""
		}

		ghApprovalList, err := service.GetGithubOrganizationsFromWhitelist(params.SignatureID, githubAccessToken)
		if err != nil {
			log.Warnf("error fetching github organization approval list entries v using signature_id: %s, error: %+v",
				params.SignatureID, err)
			return signatures.NewGetGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		return signatures.NewGetGitHubOrgWhitelistOK().WithPayload(ghApprovalList)
	})

	// Add GitHub Approval List Entries
	api.SignaturesAddGitHubOrgWhitelistHandler = signatures.AddGitHubOrgWhitelistHandlerFunc(func(params signatures.AddGitHubOrgWhitelistParams, claUser *user.CLAUser) middleware.Responder {
		session, err := sessionStore.Get(params.HTTPRequest, github.SessionStoreKey)
		if err != nil {
			log.Warnf("error retrieving session from the session store, error: %+v", err)
			return signatures.NewAddGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		githubAccessToken, ok := session.Values["github_access_token"].(string)
		if !ok {
			log.Debugf("no github access token in the session - initializing to empty string")
			githubAccessToken = ""
		}

		ghApprovalList, err := service.AddGithubOrganizationToWhitelist(params.SignatureID, params.Body, githubAccessToken)
		if err != nil {
			log.Warnf("error adding github organization %s using signature_id: %s to the whitelist, error: %+v",
				*params.Body.OrganizationID, params.SignatureID, err)
			return signatures.NewAddGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		// Create an event
		signatureModel, getSigErr := service.GetSignature(params.SignatureID)
		var projectID = ""
		var companyID = ""
		if getSigErr != nil || signatureModel == nil {
			log.Warnf("error looking up signature using signature_id: %s, error: %+v",
				params.SignatureID, getSigErr)
		}
		if signatureModel != nil {
			projectID = signatureModel.ProjectID
			companyID = signatureModel.SignatureReferenceID.String()
		}
		eventsService.LogEvent(&events.LogEventArgs{
			EventType: events.ApprovalListGithubOrganizationAdded,
			ProjectID: projectID,
			CompanyID: companyID,
			UserID:    claUser.UserID,
			EventData: &events.ApprovalListGithubOrganizationAddedEventData{
				GithubOrganizationName: utils.StringValue(params.Body.OrganizationID),
			},
		})

		return signatures.NewAddGitHubOrgWhitelistOK().WithPayload(ghApprovalList)
	})

	// Delete GitHub Approval List Entries
	api.SignaturesDeleteGitHubOrgWhitelistHandler = signatures.DeleteGitHubOrgWhitelistHandlerFunc(func(params signatures.DeleteGitHubOrgWhitelistParams, claUser *user.CLAUser) middleware.Responder {

		session, err := sessionStore.Get(params.HTTPRequest, github.SessionStoreKey)
		if err != nil {
			log.Warnf("error retrieving session from the session store, error: %+v", err)
			return signatures.NewDeleteGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		githubAccessToken, ok := session.Values["github_access_token"].(string)
		if !ok {
			log.Debugf("no github access token in the session - initializing to empty string")
			githubAccessToken = ""
		}

		ghApprovalList, err := service.DeleteGithubOrganizationFromWhitelist(params.SignatureID, params.Body, githubAccessToken)
		if err != nil {
			log.Warnf("error deleting github organization %s using signature_id: %s from the whitelist, error: %+v",
				*params.Body.OrganizationID, params.SignatureID, err)
			return signatures.NewDeleteGitHubOrgWhitelistBadRequest().WithPayload(errorResponse(err))
		}

		// Create an event
		signatureModel, getSigErr := service.GetSignature(params.SignatureID)
		var projectID = ""
		var companyID = ""
		if getSigErr != nil || signatureModel == nil {
			log.Warnf("error looking up signature using signature_id: %s, error: %+v",
				params.SignatureID, getSigErr)
		}
		if signatureModel != nil {
			projectID = signatureModel.ProjectID
			companyID = signatureModel.SignatureReferenceID.String()
		}

		eventsService.LogEvent(&events.LogEventArgs{
			EventType: events.ApprovalListGithubOrganizationDeleted,
			ProjectID: projectID,
			CompanyID: companyID,
			UserID:    claUser.UserID,
			EventData: &events.ApprovalListGithubOrganizationDeletedEventData{
				GithubOrganizationName: utils.StringValue(params.Body.OrganizationID),
			},
		})

		return signatures.NewDeleteGitHubOrgWhitelistNoContent().WithPayload(ghApprovalList)
	})

	// Get Project Signatures
	api.SignaturesGetProjectSignaturesHandler = signatures.GetProjectSignaturesHandlerFunc(func(params signatures.GetProjectSignaturesParams, claUser *user.CLAUser) middleware.Responder {
		projectSignatures, err := service.GetProjectSignatures(params)
		if err != nil {
			log.Warnf("error retrieving project signatures for projectID: %s, error: %+v",
				params.ProjectID, err)
			return signatures.NewGetProjectSignaturesBadRequest().WithPayload(errorResponse(err))
		}

		return signatures.NewGetProjectSignaturesOK().WithPayload(projectSignatures)
	})

	// Get Project Company Signatures
	api.SignaturesGetProjectCompanySignaturesHandler = signatures.GetProjectCompanySignaturesHandlerFunc(func(params signatures.GetProjectCompanySignaturesParams) middleware.Responder {
		signed, approved := true, true
		projectSignature, err := service.GetProjectCompanySignature(params.CompanyID, params.ProjectID, &signed, &approved, params.NextKey, params.PageSize)
		if err != nil {
			log.Warnf("error retrieving project signatures for project: %s, company: %s, error: %+v",
				params.ProjectID, params.CompanyID, err)
			return signatures.NewGetProjectCompanySignaturesBadRequest().WithPayload(errorResponse(err))
		}

		count := int64(1)
		if projectSignature == nil {
			count = int64(0)
		}
		response := models.Signatures{
			LastKeyScanned: "",
			ProjectID:      params.ProjectID,
			ResultCount:    count,
			Signatures:     []*models.Signature{projectSignature},
			TotalCount:     count,
		}
		return signatures.NewGetProjectCompanySignaturesOK().WithPayload(&response)
	})

	// Get Employee Project Company Signatures
	api.SignaturesGetProjectCompanyEmployeeSignaturesHandler = signatures.GetProjectCompanyEmployeeSignaturesHandlerFunc(func(params signatures.GetProjectCompanyEmployeeSignaturesParams, claUser *user.CLAUser) middleware.Responder {
		projectSignatures, err := service.GetProjectCompanyEmployeeSignatures(params)
		if err != nil {
			log.Warnf("error retrieving employee project signatures for project: %s, company: %s, error: %+v",
				params.ProjectID, params.CompanyID, err)
			return signatures.NewGetProjectCompanyEmployeeSignaturesBadRequest().WithPayload(errorResponse(err))
		}

		return signatures.NewGetProjectCompanyEmployeeSignaturesOK().WithPayload(projectSignatures)
	})

	// Get Company Signatures
	api.SignaturesGetCompanySignaturesHandler = signatures.GetCompanySignaturesHandlerFunc(func(params signatures.GetCompanySignaturesParams, claUser *user.CLAUser) middleware.Responder {
		companySignatures, err := service.GetCompanySignatures(params)
		if err != nil {
			log.Warnf("error retrieving company signatures for companyID: %s, error: %+v", params.CompanyID, err)
			return signatures.NewGetCompanySignaturesBadRequest().WithPayload(errorResponse(err))
		}

		return signatures.NewGetCompanySignaturesOK().WithPayload(companySignatures)
	})

	// Get User Signatures
	api.SignaturesGetUserSignaturesHandler = signatures.GetUserSignaturesHandlerFunc(func(params signatures.GetUserSignaturesParams, claUser *user.CLAUser) middleware.Responder {
		userSignatures, err := service.GetUserSignatures(params)
		if err != nil {
			log.Warnf("error retrieving user signatures for userID: %s, error: %+v", params.UserID, err)
			return signatures.NewGetUserSignaturesBadRequest().WithPayload(errorResponse(err))
		}

		return signatures.NewGetUserSignaturesOK().WithPayload(userSignatures)
	})
}

type codedResponse interface {
	Code() string
}

func errorResponse(err error) *models.ErrorResponse {
	code := ""
	if e, ok := err.(codedResponse); ok {
		code = e.Code()
	}

	e := models.ErrorResponse{
		Code:    code,
		Message: err.Error(),
	}

	return &e
}

func generateHTMLRedirectPage(downloadLink, claType string) string {
	return fmt.Sprintf(
		`<html lang="en">
							<head>
                               <title>The Linux Foundation – EasyCLA %s PDF Redirect</title>
                               <meta http-equiv="Refresh" content="0; url='%s'"/>
                               <meta charset="utf-8">
                               <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
                               <link rel="shortcut icon" href="https://www.linuxfoundation.org/wp-content/uploads/2017/08/favicon.png">
                               <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous"/>
                               <script src="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/js/bootstrap.min.js" integrity="sha384-JZR6Spejh4U02d8jOt6vLEHfe/JQGiRRSQQxSfFWpi1MquVdAyjUar5+76PVCmYl" crossorigin="anonymous"></script>
                            </head>
                            <body style='margin-top:20;margin-left:0;margin-right:0;'>
                              <div class="text-center">
                                <img width=300px" src="https://cla-project-logo-prod.s3.amazonaws.com/lf-horizontal-color.svg" alt="community bridge logo"/>
                              </div>
                              <h2 class="text-center">EasyCLA %s PDF Redirect Authorization</h2>
                              <p class="text-center">
                                 <a href="%s" class="btn btn-primary" role="button">Proceed To Download</a>
                              </p>
                              <p class="text-center">Link is only active for 15 minutes. Click on the CLA email to create a new download link.</p>
                            </body>
                        </html>`, claType, downloadLink, claType, downloadLink)
}
