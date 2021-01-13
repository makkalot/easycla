# Copyright The Linux Foundation and each contributor to CommunityBridge.
# SPDX-License-Identifier: MIT

"""
Easily perform signing workflows using DocuSign signing service with pydocusign.

NOTE: This integration uses DocuSign's Legacy Authentication REST API Integration.
https://developers.docusign.com/esign-rest-api/guides/post-go-live

"""

import io
import os
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import pydocusign  # type: ignore
from pydocusign.exceptions import DocuSignException  # type: ignore

import cla
from cla.controllers.lf_group import LFGroup
from cla.models import signing_service_interface, DoesNotExist
from cla.models.dynamo_models import Signature, User, \
    Project, Company, Gerrit, \
    Document, Event
from cla.models.event_types import EventType
from cla.models.s3_storage import S3Storage
from cla.utils import get_email_help_content, append_email_help_sign_off_content
from cla.user_service import UserService

api_base_url = os.environ.get('CLA_API_BASE', '')
root_url = os.environ.get('DOCUSIGN_ROOT_URL', '')
username = os.environ.get('DOCUSIGN_USERNAME', '')
password = os.environ.get('DOCUSIGN_PASSWORD', '')
integrator_key = os.environ.get('DOCUSIGN_INTEGRATOR_KEY', '')

lf_group_client_url = os.environ.get('LF_GROUP_CLIENT_URL', '')
lf_group_client_id = os.environ.get('LF_GROUP_CLIENT_ID', '')
lf_group_client_secret = os.environ.get('LF_GROUP_CLIENT_SECRET', '')
lf_group_refresh_token = os.environ.get('LF_GROUP_REFRESH_TOKEN', '')
lf_group = LFGroup(lf_group_client_url, lf_group_client_id, lf_group_client_secret, lf_group_refresh_token)


class ProjectDoesNotExist(Exception):
    pass


class CompanyDoesNotExist(Exception):
    pass


class UserDoesNotExist(Exception):
    pass


class CCLANotFound(Exception):
    pass


class UserNotWhitelisted(Exception):
    pass


class SigningError(Exception):
    def __init__(self, response):
        self.response = response


class DocuSign(signing_service_interface.SigningService):
    """
    CLA signing service backed by DocuSign.
    """
    TAGS = {'envelope_id': '{http://www.docusign.net/API/3.0}EnvelopeID',
            'type': '{http://www.docusign.net/API/3.0}Type',
            'email': '{http://www.docusign.net/API/3.0}Email',
            'user_name': '{http://www.docusign.net/API/3.0}UserName',
            'routing_order': '{http://www.docusign.net/API/3.0}RoutingOrder',
            'sent': '{http://www.docusign.net/API/3.0}Sent',
            'decline_reason': '{http://www.docusign.net/API/3.0}DeclineReason',
            'status': '{http://www.docusign.net/API/3.0}Status',
            'recipient_ip_address': '{http://www.docusign.net/API/3.0}RecipientIPAddress',
            'client_user_id': '{http://www.docusign.net/API/3.0}ClientUserId',
            'custom_fields': '{http://www.docusign.net/API/3.0}CustomFields',
            'tab_statuses': '{http://www.docusign.net/API/3.0}TabStatuses',
            'account_status': '{http://www.docusign.net/API/3.0}AccountStatus',
            'recipient_id': '{http://www.docusign.net/API/3.0}RecipientId',
            'recipient_statuses': '{http://www.docusign.net/API/3.0}RecipientStatuses',
            'recipient_status': '{http://www.docusign.net/API/3.0}RecipientStatus',
            'field_value': '{http://www.docusign.net/API/3.0}value',
            'agreement_date': '{http://www.docusign.net/API/3.0}AgreementDate',
            'signed_date': '{http://www.docusign.net/API/3.0}Signed',
            }

    def __init__(self):
        self.client = None
        self.s3storage = None

    def initialize(self, config):
        self.client = pydocusign.DocuSignClient(root_url=root_url,
                                                username=username,
                                                password=password,
                                                integrator_key=integrator_key)

        try:
            login_data = self.client.login_information()
            login_account = login_data['loginAccounts'][0]
            base_url = login_account['baseUrl']
            account_id = login_account['accountId']
            url = urlparse(base_url)
            parsed_root_url = '{}://{}/restapi/v2'.format(url.scheme, url.netloc)
        except Exception as e:
            cla.log.error('Error logging in to DocuSign: {}'.format(e))
            return {'errors': {'Error initializing DocuSign'}}

        self.client = pydocusign.DocuSignClient(root_url=parsed_root_url,
                                                account_url=base_url,
                                                account_id=account_id,
                                                username=username,
                                                password=password,
                                                integrator_key=integrator_key)
        self.s3storage = S3Storage()
        self.s3storage.initialize(None)

    def request_individual_signature(self, project_id, user_id, return_url=None, callback_url=None,
                                     preferred_email=None):
        request_info = 'project: {project_id}, user: {user_id} with return_url: {return_url}'.format(
            project_id=project_id, user_id=user_id, return_url=return_url)
        cla.log.debug('Individual Signature - creating new signature for: {}'.format(request_info))

        # Ensure this is a valid user
        user_id = str(user_id)
        try:
            user = User(preferred_email=preferred_email)
            user.load(user_id)
            cla.log.debug('Individual Signature - loaded user name: {}, '
                          'user email: {}, gh user: {}, gh id: {}'.
                          format(user.get_user_name(), user.get_user_email(), user.get_github_username(),
                                 user.get_user_github_id()))
        except DoesNotExist as err:
            cla.log.warning('Individual Signature - user ID was NOT found for: {}'.format(request_info))
            return {'errors': {'user_id': str(err)}}

        # Ensure the project exists
        try:
            project = Project()
            project.load(project_id)
            cla.log.debug('Individual Signature - loaded project id: {}, name: {}, '.
                          format(project.get_project_id(), project.get_project_name()))
        except DoesNotExist as err:
            cla.log.warning('Individual Signature - project ID NOT found for: {}'.format(request_info))
            return {'errors': {'project_id': str(err)}}

        # Check for active signature object with this project. If the user has
        # signed the most recent major version, they do not need to sign again.
        cla.log.debug('Individual Signature - loading latest user signature for user: {}, project: {}'.
                      format(user, project))
        latest_signature = user.get_latest_signature(str(project_id))
        cla.log.debug('Individual Signature - loaded latest user signature for user: {}, project: {}'.
                      format(user, project))

        cla.log.debug('Individual Signature - loading latest individual document for project: {}'.
                      format(project))
        last_document = project.get_latest_individual_document()
        cla.log.debug('Individual Signature - loaded latest individual document for project: {}'.
                      format(project))

        cla.log.debug('Individual Signature - creating default individual values for user: {}'.format(user))
        default_cla_values = create_default_individual_values(user)
        cla.log.debug('Individual Signature - created default individual values: {}'.format(default_cla_values))

        # Generate signature callback url
        cla.log.debug('Individual Signature - get active signature metadata')
        signature_metadata = cla.utils.get_active_signature_metadata(user_id)
        cla.log.debug('Individual Signature - get active signature metadata: {}'.format(signature_metadata))

        cla.log.debug('Individual Signature - get individual signature callback url')
        callback_url = cla.utils.get_individual_signature_callback_url(user_id, signature_metadata)
        cla.log.debug('Individual Signature - get individual signature callback url: {}'.format(callback_url))

        if latest_signature is not None and \
                last_document.get_document_major_version() == latest_signature.get_signature_document_major_version():
            cla.log.debug('Individual Signature - user already has a signatures with this project: {}'.
                          format(latest_signature.get_signature_id()))

            # Re-generate and set the signing url - this will update the signature record
            self.populate_sign_url(latest_signature, callback_url, default_values=default_cla_values,
                                   preferred_email=preferred_email)

            return {'user_id': user_id,
                    'project_id': project_id,
                    'signature_id': latest_signature.get_signature_id(),
                    'sign_url': latest_signature.get_signature_sign_url()}
        else:
            cla.log.debug('Individual Signature - user does NOT have a signatures with this project: {}'.
                          format(project))

        # Get signature return URL
        if return_url is None:
            return_url = cla.utils.get_active_signature_return_url(user_id, signature_metadata)
            cla.log.debug('Individual Signature - setting signature return_url to {}'.format(return_url))

        if return_url is None:
            cla.log.warning('No active signature found for user - cannot generate '
                            'return_url without knowing where the user came from')
            return {'user_id': str(user_id),
                    'project_id': str(project_id),
                    'signature_id': None,
                    'sign_url': None,
                    'error': 'No active signature found for user - cannot generate return_url without knowing where the user came from'}

        # Get latest document
        try:
            cla.log.debug('Individual Signature - loading project latest individual document...')
            document = project.get_latest_individual_document()
            cla.log.debug('Individual Signature - loaded project latest individual document: {}'.format(document))
        except DoesNotExist as err:
            cla.log.warning('Individual Signature - project individual document does NOT exist for: {}'.
                            format(request_info))
            return {'errors': {'project_id': project_id, 'message': str(err)}}

        # If the CCLA/ICLA template is missing (not created in the project console), we won't have a document
        # return an error
        if not document:
            return {'errors': {'project_id': project_id, 'message': 'missing template document'}}

        # Create new Signature object
        cla.log.debug('Individual Signature - creating new signature document '
                      'project_id: {}, user_id: {}, return_url: {}, callback_url: {}'.
                      format(project_id, user_id, return_url, callback_url))
        signature = Signature(signature_id=str(uuid.uuid4()),
                              signature_project_id=project_id,
                              signature_document_major_version=document.get_document_major_version(),
                              signature_document_minor_version=document.get_document_minor_version(),
                              signature_reference_id=user_id,
                              signature_reference_type='user',
                              signature_reference_name=user.get_user_name(),
                              signature_type='cla',
                              signature_return_url_type='Github',
                              signature_signed=False,
                              signature_approved=True,
                              signature_return_url=return_url,
                              signature_callback_url=callback_url)

        # Set signature ACL
        cla.log.debug('Individual Signature - setting ACL using user GH id: {}'.format(user.get_user_github_id()))
        signature.set_signature_acl('github:{}'.format(user.get_user_github_id()))

        # Populate sign url
        self.populate_sign_url(signature, callback_url, default_values=default_cla_values,
                               preferred_email=preferred_email)

        # Save signature
        signature.save()
        cla.log.debug('Individual Signature - Saved signature for: {}'.format(request_info))

        response = {'user_id': str(user_id),
                    'project_id': project_id,
                    'signature_id': signature.get_signature_id(),
                    'sign_url': signature.get_signature_sign_url()}

        cla.log.debug('Individual Signature - returning response: {}'.format(response))
        return response

    def request_individual_signature_gerrit(self, project_id, user_id, return_url=None):
        request_info = 'project: {project_id}, user: {user_id} with return_url: {return_url}'.format(
            project_id=project_id, user_id=user_id, return_url=return_url)
        cla.log.info('Creating new Gerrit signature for {}'.format(request_info))

        # Ensure this is a valid user
        user_id = str(user_id)
        try:
            user = User()
            user.load(user_id)
        except DoesNotExist as err:
            cla.log.warning('User ID does NOT found when requesting a signature for: {}'.format(request_info))
            return {'errors': {'user_id': str(err)}}

        # Ensure the project exists
        try:
            project = Project()
            project.load(project_id)
        except DoesNotExist as err:
            cla.log.warning('Project ID does NOT found when requesting a signature for: {}'.format(request_info))
            return {'errors': {'project_id': str(err)}}

        callback_url = self._generate_individual_signature_callback_url_gerrit(user_id)
        default_cla_values = create_default_individual_values(user)

        # Check for active signature object with this project. If the user has
        # signed the most recent major version, they do not need to sign again.
        latest_signature = user.get_latest_signature(str(project_id))
        last_document = project.get_latest_individual_document()
        if latest_signature is not None and \
                last_document.get_document_major_version() == latest_signature.get_signature_document_major_version():
            cla.log.info('User already has a signatures with this project: %s', latest_signature.get_signature_id())

            # Re-generate and set the signing url - this will update the signature record
            self.populate_sign_url(latest_signature, callback_url, default_values=default_cla_values)

            return {'user_id': user_id,
                    'project_id': project_id,
                    'signature_id': latest_signature.get_signature_id(),
                    'sign_url': latest_signature.get_signature_sign_url()}

        # the github flow has an option to have the return_url as a blank field,
        # and retrieves the return_url from the signature's metadata (github org id, PR id, etc.)
        # It will return the user to the pull request page.
        # For Gerrit users, we want the return_url to be the link to the Gerrit Instance's page.
        # Since Gerrit users will be able to make changes once they are part of the LDAP Group,
        # They do not need to be directed to a specific code submission on Gerrit.
        # Ensure return_url is set to the Gerrit instance url
        try:
            gerrits = Gerrit().get_gerrit_by_project_id(project_id)
            if len(gerrits) >= 1:
                # Github sends the user back to the pull request.
                # Gerrit should send it back to the Gerrit instance url.
                return_url = gerrits[0].get_gerrit_url()
        except DoesNotExist as err:
            cla.log.error('Gerrit Instance not found by the given project ID: %s',
                          project_id)
            return {'errors': {'project_id': str(err)}}

        try:
            document = project.get_project_individual_document()
        except DoesNotExist as err:
            cla.log.warning('Document does NOT exist when searching for ICLA for: {}'.format(request_info))
            return {'errors': {'project_id': str(err)}}

        # Create new Signature object
        signature = Signature(signature_id=str(uuid.uuid4()),
                              signature_project_id=project_id,
                              signature_document_major_version=document.get_document_major_version(),
                              signature_document_minor_version=document.get_document_minor_version(),
                              signature_reference_id=user_id,
                              signature_reference_type='user',
                              signature_reference_name=user.get_user_name(),
                              signature_type='cla',
                              signature_return_url_type='Gerrit',
                              signature_signed=False,
                              signature_approved=True,
                              signature_return_url=return_url,
                              signature_callback_url=callback_url)

        # Set signature ACL
        signature.set_signature_acl(user.get_lf_username())
        cla.log.info('Set the signature ACL for: {}'.format(request_info))

        # Populate sign url
        self.populate_sign_url(signature, callback_url, default_values=default_cla_values)

        # Save signature
        signature.save()
        cla.log.info('Saved the signature for: {}'.format(request_info))

        return {'user_id': str(user_id),
                'project_id': project_id,
                'signature_id': signature.get_signature_id(),
                'sign_url': signature.get_signature_sign_url()}

    @staticmethod
    def check_and_prepare_employee_signature(project_id, company_id, user_id) -> dict:

        # Before an employee begins the signing process, ensure that
        # 1. The given project, company, and user exists
        # 2. The company signatory has signed the CCLA for their company.
        # 3. The user is included as part of the whitelist of the CCLA that the company signed.
        # Returns an error if any of the above is false.

        fn = 'docusign_models.check_and_prepare_employee_signature'
        request_info = f'project: {project_id}, company: {company_id}, user: {user_id}'
        cla.log.info(f'{fn} - check and prepare employee signature for {request_info}')

        # Ensure the project exists
        project = Project()
        try:
            cla.log.debug(f'{fn} - loading cla group by id: {project_id}...')
            project.load(str(project_id))
            cla.log.debug(f'{fn} - cla group {project.get_project_name()} exists for: {request_info}')
        except DoesNotExist:
            cla.log.warning(f'{fn} - project does NOT exist for: {request_info}')
            return {'errors': {'project_id': f'Project ({project_id}) does not exist.'}}

        # Ensure the company exists
        company = Company()
        try:
            cla.log.debug(f'{fn} - loading company by id: {company_id}...')
            company.load(str(company_id))
            cla.log.debug(f'{fn} - company {company.get_company_name()} exists for: {request_info}')
        except DoesNotExist:
            cla.log.warning(f'{fn} - company does NOT exist for: {request_info}')
            return {'errors': {'company_id': f'Company ({company_id}) does not exist.'}}

        # Ensure the user exists
        user = User()
        try:
            cla.log.debug(f'{fn} - loading user by id: {user_id}...')
            user.load(str(user_id))
            cla.log.debug(f'{fn} - user {user.get_user_name()} exists for: {request_info}')
        except DoesNotExist:
            cla.log.warning(f'User does NOT exist for: {request_info}')
            return {'errors': {'user_id': f'User ({user_id}) does not exist.'}}

        # Ensure the company actually has a CCLA with this project.
        # ccla_signatures = Signature().get_signatures_by_project(
        #    project_id,
        #    signature_reference_type='company',
        #    signature_reference_id=company.get_company_id()
        # )
        cla.log.debug(f'{fn} - loading CCLA signatures by cla group: {project.get_project_name()} '
                      f'and company id: {company.get_company_id()}...')
        ccla_signatures = Signature().get_ccla_signatures_by_company_project(
            company_id=company.get_company_id(),
            project_id=project_id
        )
        if len(ccla_signatures) < 1:
            cla.log.warning(f'{fn} - project {project.get_project_name()} and '
                            f'company {company.get_company_name()} does not have CCLA for: {request_info}')
            return {'errors': {'missing_ccla': 'Company does not have CCLA with this project'}}

        # Add a note in the log if we have more than 1 signed and approved CCLA signature
        if len(ccla_signatures) > 1:
            cla.log.warning(f'{fn} - project {project.get_project_name()} and '
                            f'company {company.get_company_name()} has more than 1 CCLA '
                            f'signature: {len(ccla_signatures)}')

        cla.log.debug(f'{fn} CLA Group {project.get_project_name()} and company {company.get_company_name()} has '
                      f'{len(ccla_signatures)} CCLAs for: {request_info}')

        # TODO - DAD: why only grab the first one???
        ccla_signature = ccla_signatures[0]

        # Ensure user is approved for this company.
        if not user.is_approved(ccla_signature):
            # TODO: DAD - update this warning message
            cla.log.warning(f'{fn} - user is not authorized for this CCLA: {request_info}')
            return {'errors': {'ccla_approval_list': 'user not authorized for this ccla'}}

        cla.log.info(f'{fn} - user is approved for this CCLA: {request_info}')

        # Assume this company is the user's employer.
        # TODO: DAD - we should check to see if they already have a company id assigned
        if user.get_user_company_id() != company_id:
            user.set_user_company_id(str(company_id))
            event_data = (f'user {user.get_user_name()}/'
                          f'{user.get_github_username()}/'
                          f'{user.get_user_github_id()}/'
                          f'{user.get_user_id()} '
                          f'associated with company {company.get_company_name()} for '
                          f'project {project.get_project_name()}')
            event_summary_data = (f'User {user.get_user_name()}/'
                                  f'{user.get_github_username()} '
                                  f'associated with company {company.get_company_name()} for '
                                  f'project {project.get_project_name()}.')
            Event.create_event(
                event_type=EventType.UserAssociatedWithCompany,
                event_company_id=company_id,
                event_company_name=company.get_company_name(),
                event_project_id=project_id,
                event_project_name=project.get_project_name(),
                event_user_id=user.get_user_id(),
                event_data=event_data,
                event_summary=event_summary_data,
                contains_pii=True,
            )

        # Take a moment to update the user record's github information
        github_username = user.get_user_github_username()
        github_id = user.get_user_github_id()

        if github_username is None and github_id is not None:
            github_username = cla.utils.lookup_user_github_username(github_id)
            if github_username is not None:
                cla.log.debug(f'{fn} - updating user record - adding github username: {github_username}')
                user.set_user_github_username(github_username)

        # Attempt to fetch the github id based on the github username
        if github_id is None and github_username is not None:
            github_username = github_username.strip()
            github_id = cla.utils.lookup_user_github_id(github_username)
            if github_id is not None:
                cla.log.debug(f'{fn} - updating user record - adding github id: {github_id}')
                user.set_user_github_id(github_id)

        user.save()
        cla.log.info(f'{fn} - assigned company ID to user. Employee is ready to sign the CCLA: {request_info}')

        return {'success': {'the employee is ready to sign the CCLA'}}

    def request_employee_signature(self, project_id, company_id, user_id, return_url=None):

        request_info = f'project: {project_id}, company: {company_id}, user: {user_id} with return_url: {return_url}'
        cla.log.info(f'Processing request_employee_signature request with {request_info}')

        check_and_prepare_signature = self.check_and_prepare_employee_signature(project_id, company_id, user_id)
        # Check if there are any errors while preparing the signature.
        if 'errors' in check_and_prepare_signature:
            cla.log.warning(f'Error in check_and_prepare_signature with: {request_info} - '
                            f'signatures: {check_and_prepare_signature}')
            return check_and_prepare_signature

        employee_signature = Signature().get_employee_signature_by_company_project(
            company_id=company_id, project_id=project_id, user_id=user_id)
        # Return existing signature if employee has signed it
        if employee_signature is not None:
            cla.log.info(f'Employee has signed for company: {company_id}, '
                         f'request_info: {request_info} - signature: {employee_signature}')
            return employee_signature.to_dict()

        cla.log.info(f'Employee has NOT signed it for: {request_info}')

        # Requires us to know where the user came from.
        signature_metadata = cla.utils.get_active_signature_metadata(user_id)
        if return_url is None:
            cla.log.info(f'No return URL for: {request_info}')
            return_url = cla.utils.get_active_signature_return_url(user_id, signature_metadata)
            cla.log.info(f'Set return URL for: {request_info} to: {return_url}')

        # project has already been checked from check_and_prepare_employee_signature. Load project with project ID.
        project = Project()
        project.load(project_id)
        cla.log.info(f'Loaded project details for: {request_info}')

        # company has already been checked from check_and_prepare_employee_signature. Load company with company ID.
        company = Company()
        company.load(company_id)
        cla.log.info(f'Loaded company details for: {request_info}')

        # user has already been checked from check_and_prepare_employee_signature. Load user with user ID.
        user = User()
        user.load(str(user_id))

        # Get project's latest corporate document to get major/minor version numbers.
        last_document = project.get_latest_corporate_document()
        cla.log.info(f'Loaded last project document details for: {request_info}')

        # return_url may still be empty at this point - the console will deal with it
        new_signature = Signature(signature_id=str(uuid.uuid4()),
                                  signature_project_id=project_id,
                                  signature_document_minor_version=last_document.get_document_minor_version(),
                                  signature_document_major_version=last_document.get_document_major_version(),
                                  signature_reference_id=user_id,
                                  signature_reference_type='user',
                                  signature_reference_name=user.get_user_name(),
                                  signature_type='cla',
                                  signature_signed=True,
                                  signature_approved=True,
                                  signature_return_url=return_url,
                                  signature_user_ccla_company_id=company_id)
        cla.log.info(f'Created new signature document for: {request_info} - signature: {new_signature}')

        # Set signature ACL
        new_signature.set_signature_acl(f'github:{user.get_user_github_id()}')

        # Save signature
        new_signature.save()
        cla.log.info(f'Set and saved signature for: {request_info}')
        event_data = (f'employee signature created for user {user.get_user_name()}, '
                      f'company {company.get_company_name()}, '
                      f'project {project.get_project_name()}')
        Event.create_event(
            event_type=EventType.EmployeeSignatureCreated,
            event_company_id=company_id,
            event_project_id=project_id,
            event_user_id=user_id,
            event_data=event_data,
            event_summary=event_data,
            contains_pii=True,
        )

        # If the project does not require an ICLA to be signed, update the pull request and remove the active
        # signature metadata.
        if not project.get_project_ccla_requires_icla_signature():
            cla.log.info('Project does not require ICLA signature from the employee - updating PR')
            github_repository_id = signature_metadata['repository_id']
            change_request_id = signature_metadata['pull_request_id']

            # Get repository
            installation_id = cla.utils.get_installation_id_from_github_repository(github_repository_id)
            if installation_id is None:
                return {'errors': {'github_repository_id': 'The given github repository ID does not exist. '}}

            update_repository_provider(installation_id, github_repository_id, change_request_id)

            cla.utils.delete_active_signature_metadata(user_id)
        else:
            cla.log.info('Project requires ICLA signature from employee - PR has been left unchanged')

        cla.log.info(f'Returning new signature for: {request_info} - signature: {new_signature}')
        return new_signature.to_dict()

    def request_employee_signature_gerrit(self, project_id, company_id, user_id, return_url=None):

        request_info = f'project: {project_id}, company: {company_id}, user: {user_id} with return_url: {return_url}'
        cla.log.info(f'Processing request_employee_signature_gerrit request with {request_info}')

        check_and_prepare_signature = self.check_and_prepare_employee_signature(project_id, company_id, user_id)
        # Check if there are any errors while preparing the signature.
        if 'errors' in check_and_prepare_signature:
            cla.log.warning(f'Error in request_employee_signature_gerrit with: {request_info} - '
                            f'signatures: {check_and_prepare_signature}')
            return check_and_prepare_signature

        # Ensure user hasn't already signed this signature.
        employee_signature = Signature().get_employee_signature_by_company_project(
            company_id=company_id, project_id=project_id, user_id=user_id)
        # Return existing signature if employee has signed it
        if employee_signature is not None:
            cla.log.info(f'Employee has signed for company: {company_id}, '
                         f'request_info: {request_info} - signature: {employee_signature}')
            return employee_signature.to_dict()

        cla.log.info(f'Employee has NOT signed it for: {request_info}')

        # Retrieve Gerrits by Project reference ID
        try:
            gerrits = Gerrit().get_gerrit_by_project_id(project_id)
        except DoesNotExist as err:
            cla.log.error(f'Cannot load Gerrit instance for: {request_info}')
            return {'errors': {'missing_gerrit': str(err)}}

        # project has already been checked from check_and_prepare_employee_signature. Load project with project ID.
        project = Project()
        project.load(project_id)
        cla.log.info(f'Loaded project for: {request_info}')
        # company has already been checked from check_and_prepare_employee_signature. Load company with company ID.
        company = Company()
        company.load(company_id)
        cla.log.info(f'Loaded company details for: {request_info}')

        # user has already been checked from check_and_prepare_employee_signature. Load user with user ID.
        user = User()
        user.load(str(user_id))
        # Get project's latest corporate document to get major/minor version numbers.
        last_document = project.get_latest_corporate_document()

        new_signature = Signature(signature_id=str(uuid.uuid4()),
                                  signature_project_id=project_id,
                                  signature_document_minor_version=last_document.get_document_minor_version(),
                                  signature_document_major_version=last_document.get_document_major_version(),
                                  signature_reference_id=user_id,
                                  signature_reference_type='user',
                                  signature_reference_name=user.get_user_name(),
                                  signature_type='cla',
                                  signature_signed=True,
                                  signature_approved=True,
                                  signature_return_url=return_url,
                                  signature_user_ccla_company_id=company_id)

        # Set signature ACL (user already validated in 'check_and_prepare_employee_signature')
        new_signature.set_signature_acl(user.get_lf_username())

        # Save signature before adding user to the LDAP Group.
        new_signature.save()
        cla.log.info(f'Set and saved signature for: {request_info}')
        event_data = (f'employee signature created for user {user.get_user_name()}, '
                      f'company {company.get_company_name()}, '
                      f'project {project.get_project_name()}')
        Event.create_event(
            event_type=EventType.EmployeeSignatureCreated,
            event_company_id=company_id,
            event_project_id=project_id,
            event_user_id=user_id,
            event_data=event_data,
            event_summary=event_data,
            contains_pii=True,
        )

        for gerrit in gerrits:
            # For every Gerrit Instance of this project, add the user to the LDAP Group.
            # this way we are able to keep track of signed signatures when user fails to be added to the LDAP GROUP.
            group_id = gerrit.get_group_id_ccla()
            # Add the user to the LDAP Group
            try:
                lf_group.add_user_to_group(group_id, user.get_lf_username())
            except Exception as e:
                cla.log.error('Failed in adding user to the LDAP group.{} - {}'.format(e, request_info))
                return

        return new_signature.to_dict()

    def _generate_individual_signature_callback_url_gerrit(self, user_id):
        """
        Helper function to get a user's active signature callback URL for Gerrit

        """
        return os.path.join(api_base_url, 'v2/signed/gerrit/individual', str(user_id))

    def _get_corporate_signature_callback_url(self, project_id, company_id):
        """
        Helper function to get the callback_url of a CCLA signature.

        :param project_id: The ID of the project this CCLA is for.
        :type project_id: string
        :param company_id: The ID of the company signing the CCLA.
        :type company_id: string
        :return: The callback URL hit by the signing provider once the signature is complete.
        :rtype: string
        """
        return os.path.join(api_base_url, 'v2/signed/corporate', str(project_id), str(company_id))

    def handle_signing_new_corporate_signature(self, signature, project, company, user,
                                               signatory_name=None, signatory_email=None,
                                               send_as_email=False, return_url_type=None, return_url=None):
        cla.log.debug('Handle signing of new corporate signature - '
                      f'project: {project}, '
                      f'company: {company}, '
                      f'user id: {user}, '
                      f'signatory name: {signatory_name}, '
                      f'signatory email: {signatory_email} '
                      f'send email: {send_as_email}')

        # Set the CLA Managers in the schedule
        scheduleA = generate_manager_and_contributor_list([(signatory_name, signatory_email)])

        # Signatory and the Initial CLA Manager
        cla_template_values = create_default_company_values(
            company, signatory_name, signatory_email,
            user.get_user_name(), user.get_user_email(), scheduleA)

        # Ensure the project/CLA group has a corporate template document
        last_document = project.get_latest_corporate_document()
        if last_document is None or \
                last_document.get_document_major_version() is None or \
                last_document.get_document_minor_version() is None:
            cla.log.info('Contract Group {} does not have a CCLA'.format(project))
            return {'errors': {'project_id': 'Contract Group does not support CCLAs.'}}

        # No signature exists, create the new Signature.
        cla.log.info(f'Creating new signature for project {project} on company {company}')
        if signature is None:
            signature = Signature(signature_id=str(uuid.uuid4()),
                                  signature_project_id=project.get_project_id(),
                                  signature_document_minor_version=last_document.get_document_minor_version(),
                                  signature_document_major_version=last_document.get_document_major_version(),
                                  signature_reference_id=company.get_company_id(),
                                  signature_reference_type='company',
                                  signature_reference_name=company.get_company_name(),
                                  signature_type='ccla',
                                  signatory_name=signatory_name,
                                  signing_entity_name=company.get_signing_entity_name(),
                                  signature_signed=False,
                                  signature_approved=True)

        callback_url = self._get_corporate_signature_callback_url(project.get_project_id(), company.get_company_id())
        cla.log.info('Setting callback_url: %s', callback_url)
        signature.set_signature_callback_url(callback_url)

        if not send_as_email:  # get return url only for manual signing through console
            cla.log.info('Setting signature return_url to %s', return_url)
            signature.set_signature_return_url(return_url)

        # Set signature ACL
        signature.set_signature_acl(user.get_lf_username())

        self.populate_sign_url(signature, callback_url,
                               signatory_name, signatory_email,
                               send_as_email,
                               user.get_user_name(),
                               user.get_user_email(),
                               cla_template_values)

        # Save the signature
        signature.save()

        response_model = {'company_id': company.get_company_id(),
                          'project_id': project.get_project_id(),
                          'signature_id': signature.get_signature_id(),
                          'sign_url': signature.get_signature_sign_url()}
        cla.log.debug(f'Saved the signature {signature} - response mode: {response_model}')
        return response_model

    def request_corporate_signature(self, auth_user: object, project_id: object, company_id: object,
                                    send_as_email: object = False,
                                    signatory_name: object = None, signatory_email: object = None,
                                    return_url_type: object = None,
                                    return_url: object = None) -> object:

        cla.log.debug('Request corporate signature - '
                      f'project id: {project_id}, '
                      f'company id: {company_id}, '
                      f'signatory name: {signatory_name}, '
                      f'signatory email: {signatory_email} '
                      f'send email: {send_as_email}')

        # Auth user is the currently logged in user - the user who started the signing process
        # Signatory Name and Signatory Email are from the web form - will be empty if CLA Manager is the CLA Signatory

        if project_id is None:
            return {'errors': {'project_id': 'request_corporate_signature - project_id is empty'}}

        if company_id is None:
            return {'errors': {'company_id': 'request_corporate_signature - company_id is empty'}}

        if auth_user is None:
            return {'errors': {'user_error': 'request_corporate_signature - auth_user is empty'}}

        if auth_user.username is None:
            return {'errors': {'user_error': 'request_corporate_signature - auth_user.username is empty'}}

        # Ensure the user exists in our database - load the record
        cla.log.debug(f'Loading user {auth_user.username}')
        users_list = User().get_user_by_username(auth_user.username)
        if users_list is None:
            cla.log.debug(f'Unable to load auth_user by username: {auth_user.username} from the EasyCLA database.')
            # Lookup user in the platform user service...
            us = UserService
            # If found, create user record in our EasyCLA database
            cla.log.debug(f'Loading user by username: {auth_user.username} from the platform user service...')
            platform_users = us.get_users_by_username(auth_user.username)
            if platform_users is None:
                cla.log.warning(f'Unable to load auth_user by username: {auth_user.username}. '
                                'Returning an error response')
                return {'errors': {'user_error': 'user does not exist'}}
            if len(platform_users) > 1:
                cla.log.warning(f'More than one user with same username: {auth_user.username} - using first record.')

            # Grab the first user from the list - should only be one that matches the search query parameters
            platform_user = platform_users[0]
            cla.log.info(f'Found user {auth_user.username} in the platform user service: {platform_user}')
            cla.log.info(f'Creating user {auth_user.username} in the EasyCLA database...')
            user = cla.utils.get_user_instance()
            user.set_user_id(str(uuid.uuid4()))  # new internal record id
            user.set_user_external_id(platform_user.get('ID', None))
            user.set_user_name(platform_user.get('Name', None))
            # update lf_username to prevent duplication of user records
            user.set_lf_username(auth_user.username)
            # Add the emails
            platform_user_emails = platform_user.get('Emails', None)
            if len(platform_user_emails) > 0:
                email_list = []
                for platform_email in platform_user_emails:
                    email_list.append(platform_email['EmailAddress'])
                    if platform_email['IsPrimary']:
                        user.set_lf_email(platform_email['EmailAddress'])
                user.set_user_emails(email_list)
            # Add github ID, if available
            github_id = platform_user.get('GithubID', None)
            if github_id is not None:
                # Expecting: https://github.com/<github_userid>
                github_url = urlparse(github_id)
                user.set_user_github_username(github_url.path.strip('/'))
                # TODO - DAD - lookup user information in GH and fetch the
                # github ID (which is a numeric value that never changes)
                # user.set_user_github_id(...)
            # TODO - DD - we could lookup their company via platform_user['Account']['ID'] in the org service
            user.save()
            cla.log.info(f'Created user {auth_user.username} in the EasyCLA database...')
            users_list = [user]

        if len(users_list) > 1:
            cla.log.warning(f'More than one user record was returned ({len(users_list)}) from user '
                            f'username: {auth_user.username} query')

        # We've looked up this user and now have the user record - we'll use the first record we find
        # unlikely we'll have more than one
        cla_manager_user = users_list[0]

        # Add some defensive checks to ensure the Name and Email are set for the CLA Manager
        us = UserService
        cla.log.debug(f'Loading user by username: {auth_user.username} from the platform user service...')
        platform_users = us.get_users_by_username(auth_user.username)
        if platform_users is None:
            cla.log.warning(f'Unable to load auth_user by username: {auth_user.username}. '
                            'Returning an error response')
            return {'errors': {'user_error': 'user does not exist'}}
        platform_user = platform_users[0]

        if cla_manager_user.get_user_name() is None:
            # Lookup user in the platform user service...
            cla.log.warning(f'Loaded CLA Manager by username: {auth_user.username}, but '
                            'the user_name is missing from profile - required for DocuSign.')
            user_name = platform_user.get('Name', None)
            if user_name:
                cla.log.debug(f'user_name: {user_name} update for cla_manager : {auth_user.username}...')
                cla_manager_user.set_user_name(user_name)
                cla_manager_user.save()
            else:
                return {'errors': {'user_error': 'user does not have user_name'}}

        if cla_manager_user.get_user_email() is None:
            cla.log.warning(f'Loaded CLA Manager by username: {auth_user.username}, but '
                            'the user email is missing from profile - required for DocuSign.')
            # Add the emails
            platform_user_emails = platform_user.get('Emails', None)
            if len(platform_user_emails) > 0:
                email_list = []
                for platform_email in platform_user_emails:
                    email_list.append(platform_email['EmailAddress'])
                    if platform_email['IsPrimary']:
                        cla_manager_user.set_lf_email(platform_email['EmailAddress'])
                cla_manager_user.set_user_emails(email_list)
                cla_manager_user.save()
            else:
                return {'errors': {'user_error': 'user does not have an email'}}

        cla.log.debug(f'Loaded user {cla_manager_user} - this is our CLA Manager')
        # Ensure the project exists
        project = Project()
        try:
            cla.log.debug(f'Loading project {project_id}')
            project.load(str(project_id))
            cla.log.debug(f'Loaded project {project}')
        except DoesNotExist as err:
            cla.log.warning(f'Unable to load project by id: {project_id}. '
                            'Returning an error response')
            return {'errors': {'project_id': str(err)}}

        # Ensure the company exists
        company = Company()
        try:
            cla.log.debug(f'Loading company {company_id}')
            company.load(str(company_id))
            cla.log.debug(f'Loaded company {company}')
        except DoesNotExist as err:
            cla.log.warning(f'Unable to load company by id: {company_id}. '
                            'Returning an error response')
            return {'errors': {'company_id': str(err)}}

        # Decision Point:
        # If no signatory name/email passed in, then the specified user (CLA Manager) IS also the CLA Signatory
        if signatory_name is None or signatory_email is None:
            cla.log.debug(f'No CLA Signatory specified for project {project}, company {company}.'
                          f' User: {cla_manager_user} will be the CLA Authority.')
            signatory_name = cla_manager_user.get_user_name()
            signatory_email = cla_manager_user.get_user_email()

        # Attempt to load the CLA Corporate Signature Record for this project/company combination
        cla.log.debug(f'Searching for existing CCLA signatures for project: {project_id} '
                      f'with company: {company_id} '
                      'type: company, signed: <not specified>, approved: true')
        signatures = Signature().get_signatures_by_project(project_id=project_id,
                                                           signature_approved=True,
                                                           signature_type='company',
                                                           signature_reference_id=company_id)

        # Determine if we have any signed signatures matching this CCLA
        # May have some signed and/or started/not-signed due to prior bug
        have_signed_sig = False
        for sig in signatures:
            if sig.get_signature_signed():
                have_signed_sig = True
                break

        if have_signed_sig:
            cla.log.warning(f'One or more corporate valid signatures exist for '
                            f'project: {project}, company: {company} - '
                            f'{len(signatures)} total')
            return {'errors': {'signature_id': 'Company has already signed CCLA with this project'}}

        # No existing corporate signatures - signed or not signed
        if len(signatures) == 0:
            cla.log.debug(f'No CCLA signatures on file for project: {project_id}, company: {company_id}')
            return self.handle_signing_new_corporate_signature(
                signature=None, project=project, company=company, user=cla_manager_user,
                signatory_name=signatory_name, signatory_email=signatory_email,
                send_as_email=send_as_email, return_url_type=return_url_type, return_url=return_url)

        cla.log.debug(f'Previous unsigned CCLA signatures on file for project: {project_id}, company: {company_id}')
        # TODO: should I delete all but one?
        return self.handle_signing_new_corporate_signature(
            signature=signatures[0], project=project, company=company, user=cla_manager_user,
            signatory_name=signatory_name, signatory_email=signatory_email,
            send_as_email=send_as_email, return_url_type=return_url_type, return_url=return_url)

    def populate_sign_url(self, signature, callback_url=None,
                          authority_or_signatory_name=None,
                          authority_or_signatory_email=None,
                          send_as_email=False,
                          cla_manager_name=None, cla_manager_email=None,
                          default_values: Optional[Dict[str, Any]] = None,
                          preferred_email: str = None):  # pylint: disable=too-many-locals

        sig_type = signature.get_signature_reference_type()

        cla.log.debug(f'populate_sign_url - Populating sign_url for signature {signature.get_signature_id()} '
                      f'using callback: {callback_url} '
                      f'with authority_or_signatory_name {authority_or_signatory_name} '
                      f'with authority_or_signatory_email {authority_or_signatory_email} '
                      f'with cla manager name: {cla_manager_name} '
                      f'with cla manager email: {cla_manager_email} '
                      f'send as email: {send_as_email} '
                      f'reference type: {sig_type}')

        # Depending on the signature type - we'll need either the company or the user record
        company = Company()
        #  by passing the preferred email we make sure the get_user_email will return it if present
        user = User(preferred_email=preferred_email)

        # We use user name/email non-email docusign user ICLA
        user_signature_name = 'Unknown'
        user_signature_email = 'Unknown'

        cla.log.debug(f'populate_sign_url - {sig_type} - processing signing request...')

        if sig_type == 'company':
            # For CCLA - use provided CLA Manager information
            user_signature_name = cla_manager_name
            user_signature_email = cla_manager_email
            cla.log.debug(f'populate_sign_url - {sig_type} - user_signature name/email will be CLA Manager name/info: '
                          f'{user_signature_name} / {user_signature_email}...')

            try:
                # Grab the company id from the signature
                cla.log.debug('populate_sign_url - CCLA - '
                              f'Loading company id: {signature.get_signature_reference_id()}')
                company.load(signature.get_signature_reference_id())
                cla.log.debug(f'populate_sign_url - {sig_type} - loaded company: {company}')
            except DoesNotExist:
                cla.log.warning(f'populate_sign_url - {sig_type} - '
                                'No CLA manager associated with this company - can not sign CCLA')
                return
            except Exception as e:
                cla.log.warning(f'populate_sign_url - {sig_type} - No CLA manager lookup error: {e}')
                return
        elif sig_type == 'user':
            if not send_as_email:
                try:
                    cla.log.debug(f'populate_sign_url - {sig_type} - '
                                  f'loading user by reference id: {signature.get_signature_reference_id()}')
                    user.load(signature.get_signature_reference_id())
                    cla.log.debug(f'populate_sign_url - {sig_type} - loaded user by '
                                  f'id: {user.get_user_id()}, '
                                  f'name: {user.get_user_name()}, '
                                  f'email: {user.get_user_email()}')
                    if not user.get_user_name() is None:
                        user_signature_name = user.get_user_name()
                    if not user.get_user_email() is None:
                        user_signature_email = user.get_user_email()
                except DoesNotExist:
                    cla.log.warning(f'populate_sign_url - {sig_type} - no user associated with this signature '
                                    f'id: {signature.get_signature_reference_id()} - can not sign ICLA')
                    return
                except Exception as e:
                    cla.log.warning(f'populate_sign_url - {sig_type} - no user associated with this signature - '
                                    f'id: {signature.get_signature_reference_id()}, '
                                    f'error: {e}')
                    return

                cla.log.debug(
                    f'populate_sign_url - {sig_type} - user_signature name/email will be user from signature: '
                    f'{user_signature_name} / {user_signature_email}...')
        else:
            cla.log.warning(f'populate_sign_url - unsupported signature type: {sig_type}')
            return

        # Fetch the document template to sign.
        project = Project()
        cla.log.debug(f'populate_sign_url - {sig_type} - '
                      f'loading project by id: {signature.get_signature_project_id()}')
        project.load(signature.get_signature_project_id())
        cla.log.debug(f'populate_sign_url - {sig_type} - '
                      f'loaded project by id: {signature.get_signature_project_id()} - '
                      f'project: {project}')

        # Load the appropriate document
        if sig_type == 'company':
            cla.log.debug(f'populate_sign_url - {sig_type} - loading project_corporate_document...')
            document = project.get_project_corporate_document()
            if document is None:
                cla.log.error(f'populate_sign_url - {sig_type} - Could not get sign url for project: {project}. '
                              'Project has no corporate CLA document set. Returning...')
                return
            cla.log.debug(f'populate_sign_url - {sig_type} - loaded project_corporate_document...')
        else:  # sig_type == 'user'
            cla.log.debug(f'populate_sign_url - {sig_type} - loading project_individual_document...')
            document = project.get_project_individual_document()
            if document is None:
                cla.log.error(f'populate_sign_url - {sig_type} - Could not get sign url for project: {project}. '
                              'Project has no individual CLA document set. Returning...')
                return
            cla.log.debug(f'populate_sign_url - {sig_type} - loaded project_individual_document...')

        # Void the existing envelope to prevent multiple envelopes pending for a signer. 
        envelope_id = signature.get_signature_envelope_id()
        if envelope_id is not None:
            try:
                message = ('You are getting this message because your DocuSign Session '
                           f'for project {project.get_project_name()} expired. A new session will be in place for '
                           'your signing process.')
                cla.log.debug(message)
                self.client.void_envelope(envelope_id, message)
            except Exception as e:
                cla.log.warning(f'populate_sign_url - {sig_type} - DocuSign error while voiding the envelope - '
                                f'regardless, continuing on..., error: {e}')

        # Not sure what should be put in as documentId.
        document_id = uuid.uuid4().int & (1 << 16) - 1  # Random 16bit integer -.pylint: disable=no-member
        tabs = get_docusign_tabs_from_document(document, document_id, default_values=default_values)

        if send_as_email:
            cla.log.warning(f'populate_sign_url - {sig_type} - assigning signatory name/email: '
                            f'{authority_or_signatory_name} / {authority_or_signatory_email}')
            # Sending email to authority
            signatory_email = authority_or_signatory_email
            signatory_name = authority_or_signatory_name

            # Not assigning a clientUserId sends an email.
            project_name = project.get_project_name()
            company_name = company.get_company_name()

            cla.log.debug(f'populate_sign_url - {sig_type} - sending document as email with '
                          f'name: {signatory_name}, email: {signatory_email} '
                          f'project name: {project_name}, company: {company_name}')

            email_subject = f'EasyCLA: CLA Signature Request for {project_name}'
            email_body = f'<p>Hello {signatory_name},<p>'
            email_body += f'<p>This is a notification email from EasyCLA regarding the project {project_name}. {cla_manager_name} has designated you as being an authorized signatory for {company_name}. In order for employees of your company to contribute to the open source project {project_name}, they must do so under a Contributor License Agreement signed by someone with authority to sign on behalf of your company.</p>'
            email_body += f'<p>After you sign, {cla_manager_name} (as the initial CLA Manager for your company) will be able to maintain the list of specific employees authorized to contribute to the project under this signed CLA.</p>'
            email_body += f'<p>If you are authorized to sign on your company’s behalf, and if you approve {cla_manager_name} as your initial CLA Manager for {project_name}, please click the link below to review and sign the CLA.If you have questions, or if you are not an authorized signatory of this company, please contact the requester at {cla_manager_email}.</p>'
            email_body = append_email_help_sign_off_content(email_body, project.get_version())
            cla.log.debug(f'populate_sign_url - {sig_type} - generating a docusign signer object form email with'
                          f'name: {signatory_name}, email: {signatory_email}, subject: {email_subject}')
            signer = pydocusign.Signer(email=signatory_email,
                                       name=signatory_name,
                                       recipientId=1,
                                       tabs=tabs,
                                       emailSubject=email_subject,
                                       emailBody=email_body,
                                       supportedLanguage='en',
                                       )
        else:
            # This will be the Initial CLA Manager
            signatory_name = user_signature_name
            signatory_email = user_signature_email

            # Assigning a clientUserId does not send an email.
            # It assumes that the user handles the communication with the client.
            # In this case, the user opened the docusign document to manually sign it.
            # Thus the email does not need to be sent.
            cla.log.debug(f'populate_sign_url - {sig_type} - generating a docusign signer object with '
                          f'name: {signatory_name}, email: {signatory_email}')

            # Max length for emailSubject is 100 characters - guard/truncate if necessary
            email_subject = f'EasyCLA: CLA Signature Request for {project.get_project_name()}'
            email_subject = (email_subject[:97] + '...') if len(email_subject) > 100 else email_subject
            # Update Signed for label according to signature_type (company or name)
            if sig_type == 'company':
                user_identifier = company.get_company_name()
            else:
                if signatory_name == 'Unknown' or signatory_name == None:
                    user_identifier = signatory_email
                else:
                    user_identifier = signatory_name
            signer = pydocusign.Signer(email=signatory_email, name=signatory_name,
                                       recipientId=1, clientUserId=signature.get_signature_id(),
                                       tabs=tabs,
                                       emailSubject=email_subject,
                                       emailBody='CLA Sign Request for {}'.format(user_identifier),
                                       supportedLanguage='en',
                                       )

        content_type = document.get_document_content_type()
        if document.get_document_s3_url() is not None:
            pdf = self.get_document_resource(document.get_document_s3_url())
        elif content_type.startswith('url+'):
            pdf_url = document.get_document_content()
            pdf = self.get_document_resource(pdf_url)
        else:
            content = document.get_document_content()
            pdf = io.BytesIO(content)

        doc_name = document.get_document_name()
        cla.log.debug(f'populate_sign_url - {sig_type} - docusign document '
                      f'name: {doc_name}, id: {document_id}, content type: {content_type}')
        document = pydocusign.Document(name=doc_name, documentId=document_id, data=pdf)

        if callback_url is not None:
            # Webhook properties for callbacks after the user signs the document.
            # Ensure that a webhook is returned on the status "Completed" where
            # all signers on a document finish signing the document.
            recipient_events = [{"recipientEventStatusCode": "Completed"}]
            event_notification = pydocusign.EventNotification(url=callback_url,
                                                              loggingEnabled=True,
                                                              recipientEvents=recipient_events)
            envelope = pydocusign.Envelope(
                documents=[document],
                emailSubject=f'EasyCLA: CLA Signature Request for {project.get_project_name()}',
                emailBlurb='CLA Sign Request',
                eventNotification=event_notification,
                status=pydocusign.Envelope.STATUS_SENT,
                recipients=[signer])
        else:
            envelope = pydocusign.Envelope(
                documents=[document],
                emailSubject=f'EasyCLA: CLA Signature Request for {project.get_project_name()}',
                emailBlurb='CLA Sign Request',
                status=pydocusign.Envelope.STATUS_SENT,
                recipients=[signer])

        envelope = self.prepare_sign_request(envelope)

        if not send_as_email:
            recipient = envelope.recipients[0]

            # The URL the user will be redirected to after signing.
            # This route will be in charge of extracting the signature's return_url and redirecting.
            return_url = os.path.join(api_base_url, 'v2/return-url', str(recipient.clientUserId))

            cla.log.debug(f'populate_sign_url - {sig_type} - generating signature sign_url, '
                          f'using return-url as: {return_url}')
            sign_url = self.get_sign_url(envelope, recipient, return_url)
            cla.log.debug(f'populate_sign_url - {sig_type} - setting signature sign_url as: {sign_url}')
            signature.set_signature_sign_url(sign_url)

        # Save Envelope ID in signature.
        cla.log.debug(f'populate_sign_url - {sig_type} - saving signature to database...')
        signature.set_signature_envelope_id(envelope.envelopeId)
        signature.save()
        cla.log.debug(f'populate_sign_url - {sig_type} - complete')

    def signed_individual_callback(self, content, installation_id, github_repository_id, change_request_id):
        """
        Will be called on ICLA signature callback, but also when a document has been
        opened by a user - no action required then.
        """
        cla.log.debug(f'signed_individual_callback - Docusign ICLA signed callback POST data: {content}')
        tree = ET.fromstring(content)
        # Get envelope ID.
        envelope_id = tree.find('.//' + self.TAGS['envelope_id']).text
        # Assume only one signature per signature.
        signature_id = tree.find('.//' + self.TAGS['client_user_id']).text
        signature = cla.utils.get_signature_instance()
        try:
            signature.load(signature_id)
        except DoesNotExist:
            cla.log.error('signed_individual_callback - DocuSign ICLA callback returned signed info on '
                          f'invalid signature: {content}')
            return
        # Iterate through recipients and update the signature signature status if changed.
        elem = tree.find('.//' + self.TAGS['recipient_statuses'] + '/' + self.TAGS['recipient_status'])
        status = elem.find(self.TAGS['status']).text
        if status == 'Completed' and not signature.get_signature_signed():
            cla.log.info(f'signed_individual_callback - ICLA signature signed ({signature_id}) - '
                         'Notifying repository service provider')
            signature.set_signature_signed(True)
            populate_signature_from_icla_callback(content, tree, signature)
            # Save signature
            signature.save()

            # Update the repository provider with this change - this will update the comment (if necessary)
            # and the status - do this early in the flow as the user will be immediately redirected back
            update_repository_provider(installation_id, github_repository_id, change_request_id)
            # Send user their signed document.
            user = User()
            user.load(signature.get_signature_reference_id())
            # Update user name in case is empty.
            if not user.get_user_name():
                full_name_field = tree.find(".//*[@name='full_name']")
                full_name = full_name_field.find(self.TAGS['field_value'])
                if full_name:
                    cla.log.info(f'Updating user: {user.get_user_github_id()} with name : {full_name.text}')
                    user.set_user_name(full_name.text)
                    user.save()
            # Remove the active signature metadata.
            cla.utils.delete_active_signature_metadata(user.get_user_id())
            # Get signed document
            document_data = self.get_signed_document(envelope_id, user)
            # Send email with signed document.
            self.send_signed_document(signature, document_data, user, icla=True)

            # Verify user id exist for saving on storage
            user_id = user.get_user_id()
            if user_id is None:
                cla.log.warning('signed_individual_callback - '
                                'Missing user_id on ICLA for saving signed file on s3 storage.')
                raise SigningError('Missing user_id on ICLA for saving signed file on s3 storage.')

            # Store document on S3
            project_id = signature.get_signature_project_id()
            self.send_to_s3(document_data, project_id, signature_id, 'icla', user_id)

            # Log the event
            try:
                # Load the Project by ID and send audit event
                project = Project()
                project.load(signature.get_signature_project_id())
                event_data = (f'individual signature of user {user.get_user_name()} '
                              f'signed for project {project.get_project_name()}')
                Event.create_event(
                    event_type=EventType.IndividualSignatureSigned,
                    event_project_id=signature.get_signature_project_id(),
                    event_company_id=None,
                    event_user_id=signature.get_signature_reference_id(),
                    event_data=event_data,
                    event_summary=event_data,
                    contains_pii=False,
                )
            except DoesNotExist as err:
                msg = (f'signed_individual_callback - '
                       f'unable to load project by CLA Group ID: {signature.get_signature_project_id()}, '
                       f'unable to send audit event, error: {err}')
                cla.log.warning(msg)
                return

    def signed_individual_callback_gerrit(self, content, user_id):
        cla.log.debug('signed_individual_callback_gerrit - '
                      f'Docusign Gerrit ICLA signed callback POST data: {content}')
        tree = ET.fromstring(content)
        # Get envelope ID.
        envelope_id = tree.find('.//' + self.TAGS['envelope_id']).text
        # Assume only one signature per signature.
        signature_id = tree.find('.//' + self.TAGS['client_user_id']).text
        signature = cla.utils.get_signature_instance()
        try:
            signature.load(signature_id)
        except DoesNotExist:
            cla.log.error('signed_individual_callback_gerrit - DocuSign Gerrit ICLA callback returned signed info '
                          f'on invalid signature: {content}')
            return
        # Iterate through recipients and update the signature signature status if changed.
        elem = tree.find('.//' + self.TAGS['recipient_statuses'] +
                         '/' + self.TAGS['recipient_status'])
        status = elem.find(self.TAGS['status']).text
        if status == 'Completed' and not signature.get_signature_signed():
            cla.log.info(f'signed_individual_callback_gerrit - ICLA signature signed ({signature_id}) - '
                         'Notifying repository service provider')
            # Get User
            user = cla.utils.get_user_instance()
            user.load(user_id)

            cla.log.debug('signed_individual_callback_gerrit - updating signature in database - '
                          'setting signed=true...')
            # Save signature before adding user to LDAP Groups.
            signature.set_signature_signed(True)
            signature.save()

            # Load the Project by ID and send audit event
            project = Project()
            try:
                project.load(signature.get_signature_project_id())
                event_data = (f'individual signature of user {user.get_user_name()} '
                              f'signed for project {project.get_project_name()}')
                Event.create_event(
                    event_type=EventType.IndividualSignatureSigned,
                    event_project_id=signature.get_signature_project_id(),
                    event_company_id=None,
                    event_user_id=user.get_user_id(),
                    event_data=event_data,
                    event_summary=event_data,
                    contains_pii=False,
                )
            except DoesNotExist as err:
                msg = (f'signed_individual_callback_gerrit - '
                       f'unable to load project by CLA Group ID: {signature.get_signature_project_id()}, '
                       f'unable to send audit event, error: {err}')
                cla.log.warning(msg)
                return

            gerrits = Gerrit().get_gerrit_by_project_id(signature.get_signature_project_id())
            for gerrit in gerrits:
                # Get Gerrit Group ID
                group_id = gerrit.get_group_id_icla()

                # Check if Group id is none
                if group_id is not None:
                    lf_username = user.get_lf_username()
                    # Add the user to the LDAP Group
                    try:
                        lf_group.add_user_to_group(group_id, lf_username)
                    except Exception as e:
                        cla.log.error('signed_individual_callback_gerrit - '
                                      f'Failed in adding user to the LDAP group: {e}')
                        return

            # Get signed document
            document_data = self.get_signed_document(envelope_id, user)
            # Send email with signed document.
            self.send_signed_document(signature, document_data, user, icla=True)

            # Verify user id exist for saving on storage
            if user_id is None:
                cla.log.warning('signed_individual_callback_gerrit - '
                                'Missing user_id on ICLA for saving signed file on s3 storage')
                raise SigningError('Missing user_id on ICLA for saving signed file on s3 storage.')

            # Store document on S3
            project_id = signature.get_signature_project_id()
            self.send_to_s3(document_data, project_id, signature_id, 'icla', user_id)
            cla.log.debug('signed_individual_callback_gerrit - uploaded ICLA document to s3')

    def signed_corporate_callback(self, content, project_id, company_id):
        """
        Will be called on CCLA signature callback, but also when a document has been
        opened by a user - no action required then.
        """
        param_str = f'project_id={project_id}, company_id={company_id}'
        cla.log.debug(f'signed_corporate_callback - DocuSign CCLA signed callback POST data: {content} '
                      f'with params: {param_str}')
        tree = ET.fromstring(content)
        # Get envelope ID.
        envelope_id = tree.find('.//' + self.TAGS['envelope_id']).text

        # Load the Project by ID
        project = Project()
        try:
            project.load(project_id)
        except DoesNotExist as err:
            msg = (f'signed_corporate_callback - Docusign callback failed: invalid project ID, params: {param_str}, '
                   f'error: {err}')
            cla.log.warning(msg)
            return {'errors': {'error': msg}}

        # Get Company with company ID.
        company = Company()
        try:
            company.load(str(company_id))
        except DoesNotExist as err:
            msg = (f'signed_corporate_callback - Docusign callback failed: invalid company ID, params: {param_str}, '
                   f'error: {err}')
            cla.log.warning(msg)
            return {'errors': {'error': msg}}

        # Assume only one signature per signature.
        client_user_id = tree.find('.//' + self.TAGS['client_user_id'])
        if client_user_id is not None:
            signature_id = client_user_id.text
            signature = cla.utils.get_signature_instance()
            try:
                signature.load(signature_id)
            except DoesNotExist as err:
                msg = (f'signed_corporate_callback - DocuSign callback returned signed info on an '
                       f'invalid signature: {content} with params: {param_str}')
                cla.log.warning(msg)
                return {'errors': {'error': msg}}
        else:
            # If client_user_id is None, the callback came from the email that finished signing. 
            # Retrieve the latest signature with projectId and CompanyId.
            signature = company.get_latest_signature(str(project_id))
            signature_id = signature.get_signature_id()

        # Get User
        user = cla.utils.get_user_instance()
        if signature.get_signature_reference_type() == 'user':
            # ICLA
            cla.log.debug(f'signed_corporate_callback - {signature.get_signature_reference_type()} - '
                          f'loading user by id: {signature.get_signature_reference_id()} for params: {param_str}')
            user.load(signature.get_signature_reference_id())
        elif signature.get_signature_reference_type() == 'company':
            # CCLA
            cla.log.debug(f'signed_corporate_callback - {signature.get_signature_reference_type()} - '
                          f'loading CLA Managers with params: {param_str}...')
            # Should have only 1 CLA Manager assigned at this point - grab the list of cla managers from the signature
            # record
            cla_manager_list = list(signature.get_signature_acl())

            # Load the user record of the initial CLA Manager
            if len(cla_manager_list) > 0:
                cla.log.debug(f'signed_corporate_callback - loading user: {cla_manager_list[0]} '
                              f'with params: {param_str}...')
                user_list = user.get_user_by_username(cla_manager_list[0])
                if user_list is None:
                    msg = (f'signed_corporate_callback - CLA Manager not assign for signature: {signature} '
                           f'with params: {param_str}')
                    cla.log.warning(msg)
                    return {'errors': {'error': msg}}
                else:
                    user = user_list[0]
            else:
                msg = (f'signed_corporate_callback - CLA Manager not assign for signature: {signature} '
                       f'with params: {param_str}')
                cla.log.warning(msg)
                return {'errors': {'error': msg}}

        # Iterate through recipients and update the signature signature status if changed.
        elem = tree.find('.//' + self.TAGS['recipient_statuses'] +
                         '/' + self.TAGS['recipient_status'])
        status = elem.find(self.TAGS['status']).text

        if status == 'Completed' and not signature.get_signature_signed():
            cla.log.info(f'signed_corporate_callback - {signature.get_signature_reference_type()} - '
                         f'CLA signature signed ({signature_id}) - setting signature signed attribute to true, '
                         f'params: {param_str}')
            # Note: cla-manager role assignment and cla-manager-designee cleanup is handled in the DB trigger handler
            # upon save with the signature signed flag transition to true...
            signature.set_signature_signed(True)
            populate_signature_from_ccla_callback(content, tree, signature)
            signature.save()

            # Update our event/activity log
            if signature.get_signature_reference_type() == 'user':
                event_data = (f'individual signature of user {user.get_user_name()} '
                              f'signed for project {project.get_project_name()}, '
                              f'params: {param_str}')
                event_summary = (f'Individual signature of user {user.get_user_name()} '
                                 f'signed for project {project.get_project_name()}.')
                Event.create_event(
                    event_type=EventType.IndividualSignatureSigned,
                    event_project_id=project_id,
                    event_company_id=None,
                    event_user_id=user.get_user_id(),
                    event_data=event_data,
                    event_summary=event_summary,
                    contains_pii=False,
                )
            elif signature.get_signature_reference_type() == 'company':
                event_data = (f'corporate signature '
                              f'signed for project {project.get_project_name()} '
                              f'and company {company.get_company_name()} '
                              f'by user {user.get_user_name()}, '
                              f'params: {param_str}')
                event_summary = (f'A corporate signature '
                                 f'was signed for project {project.get_project_name()} '
                                 f'and company {company.get_company_name()} '
                                 f'by user {user.get_user_name()}.')
                Event.create_event(
                    event_type=EventType.CompanySignatureSigned,
                    event_project_id=project_id,
                    event_company_id=company.get_company_id(),
                    event_user_id=user.get_user_id(),
                    event_data=event_data,
                    event_summary=event_summary,
                    contains_pii=False,
                )

            # Check if the callback is for a Gerrit Instance
            try:
                gerrits = Gerrit().get_gerrit_by_project_id(signature.get_signature_project_id())
            except DoesNotExist:
                gerrits = []

            # Get LF user name. 
            lf_username = user.get_lf_username()
            for gerrit in gerrits:
                # Get Gerrit Group ID
                group_id = gerrit.get_group_id_ccla()

                # Check if Group id is none
                if group_id is not None:
                    # Add the user to the LDAP Group (corporate authority)
                    try:
                        lf_group.add_user_to_group(group_id, lf_username)
                    except Exception as e:
                        cla.log.error(f'signed_corporate_callback - {signature.get_signature_reference_type()} - '
                                      f'Failed in adding user to the LDAP group: {e}, '
                                      f'params: {param_str}')
                        return

            # Get signed document - will be either:
            # ICLA - user is the individual contributor
            # CCLA - user is the initial CLA Manager
            document_data = self.get_signed_document(envelope_id, user)
            # Send email with signed document.
            self.send_signed_document(signature, document_data, user, icla=False)

            # verify company_id is not none
            if company_id is None:
                cla.log.warning('signed_corporate_callback - '
                                'Missing company_id on CCLA for saving signed file on s3 storage, '
                                f'params: {param_str}')
                raise SigningError('Missing company_id on CCLA for saving signed file on s3 storage.')

            # Store document on S3
            cla.log.debug(f'signed_corporate_callback - uploading CCLA document to s3, params: {param_str}...')
            self.send_to_s3(document_data, project_id, signature_id, 'ccla', company_id)
            cla.log.debug(f'signed_corporate_callback - uploaded CCLA document to s3, params: {param_str}')
            cla.log.debug(f'signed_corporate_callback - DONE!, params: {param_str}')

    def get_signed_document(self, envelope_id, user):
        """Helper method to get the signed document from DocuSign."""

        cla.log.debug(f'get_signed_document - fetching signed CLA document for envelope: {envelope_id}')
        envelope = pydocusign.Envelope()
        envelope.envelopeId = envelope_id

        try:
            documents = envelope.get_document_list(self.client)
        except Exception as err:
            cla.log.error('get_signed_document - unknown error when trying to load signed document: %s', str(err))
            return

        if documents is None or len(documents) < 1:
            cla.log.error(f'get_signed_document - could not find signed document'
                          f'envelope {envelope_id} and user {user.get_user_email()}')
            return

        document = documents[0]
        if 'documentId' not in document:
            cla.log.error(f'get_signed_document - not document ID found in document response: {document}')
            return

        try:
            # TODO: Also send the signature certificate? envelope.get_certificate()
            document_file = envelope.get_document(document['documentId'], self.client)
            return document_file.read()
        except Exception as err:
            cla.log.error('get_signed_document - unknown error when trying to fetch signed document content '
                          f'for document ID {document["documentId"]}, error: {err}')
            return

    def send_signed_document(self, signature, document_data, user, icla=True):
        """Helper method to send the user their signed document."""

        # Check if the user's email is public
        recipient = cla.utils.get_public_email(user)
        if not recipient:
            cla.log.debug(f'No email found for user : {user.get_user_id()}')
            return

        # Load and ensure the CLA Group/Project record exists
        try:
            project = Project()
            project.load(signature.get_signature_project_id())
        except DoesNotExist as err:
            cla.log.warning(f'send_signed_document - unable to load project by id: {project.get_project_id()} - '
                            'unable to send email to user')
            return

        # subject = 'EasyCLA: Signed Document'
        # body = 'Thank you for signing the CLA! Your signed document is attached to this email.'
        if icla:
            pdf_link = (f'{cla.conf["API_BASE_URL"]}/v3/'
                        f'signatures/{project.get_project_id()}/'
                        f'{user.get_user_id()}/icla/pdf')
        else:
            pdf_link = (f'{cla.conf["API_BASE_URL"]}/v3/'
                        f'signatures/{project.get_project_id()}/'
                        f'{signature.get_signature_reference_id()}/ccla/pdf')
        subject = f'EasyCLA: CLA Signature Signed for {project.get_project_name()}'
        body = f'''
            <p>Hello {"Contributor" if icla else "CLA Signatory"},</p>
            <p>This is a notification email from EasyCLA regarding the project {project.get_project_name()}.</p>
            <p>Thank you for signing the CLA.  You can download the PDF document
               <a href="{pdf_link}" target="_blank" alt="{'ICLA' if icla else 'CCLA'} Document Link">
               from our website<a>.
            </p>
            '''
        body = append_email_help_sign_off_content(body, project.get_version())

        # Third, send the email.
        cla.log.info(f'Sending signed CLA document to {recipient} with subject: {subject}')
        cla.utils.get_email_service().send(subject, body, recipient)

    def send_to_s3(self, document_data, project_id, signature_id, cla_type, identifier):
        # cla_type could be: icla or ccla (String)
        # identifier could be: user_id or company_id
        filename = str.join('/',
                            ('contract-group', str(project_id), cla_type, str(identifier), str(signature_id) + '.pdf'))
        cla.log.debug(f'send_to_s3 - uploading document with filename: {filename}')
        self.s3storage.store(filename, document_data)

    def get_document_resource(self, url):  # pylint: disable=no-self-use
        """
        Mockable method to fetch the PDF for signing.

        :param url: The URL of the PDF file to sign.
        :type url: string
        :return: A resource that can be read()'d.
        :rtype: Resource
        """
        return urllib.request.urlopen(url)

    def prepare_sign_request(self, envelope):
        """
        Mockable method for sending a signature request to DocuSign.

        :param envelope: The envelope to send to DocuSign.
        :type envelope: pydocusign.Envelope
        :return: The new envelope to work with after the request has been sent.
        :rtype: pydocusign.Envelope
        """
        try:
            self.client.create_envelope_from_documents(envelope)
            envelope.get_recipients()
            return envelope
        except DocuSignException as err:
            cla.log.error(f'prepare_sign_request - error while fetching DocuSign envelope recipients: {err}')

    def get_sign_url(self, envelope, recipient, return_url):  # pylint:disable=no-self-use
        """
        Mockable method for getting a signing url.

        :param envelope: The envelope in question.
        :type envelope: pydocusign.Envelope
        :param recipient: The recipient inside this envelope.
        :type recipient: pydocusign.Recipient
        :param return_url: The URL to return the user after successful signing.
        :type return_url: string
        :return: A URL for the recipient to hit for signing.
        :rtype: string
        """
        return envelope.post_recipient_view(recipient, returnUrl=return_url)


class MockDocuSign(DocuSign):
    """
    Mock object to test DocuSign service implementation.
    """

    def get_document_resource(self, url):
        """
        Need to implement fake resource here.
        """
        return open(cla.utils.get_cla_path() + '/tests/resources/test.pdf', 'rb')

    def prepare_sign_request(self, envelope):
        """
        Don't actually send the request when running tests.
        """
        recipients = []
        for recipient in envelope.recipients:
            recip = lambda: None
            recip.clientUserId = recipient.clientUserId
            recipients.append(recip)
        envelope = MockRecipient()
        envelope.recipients = recipients
        return envelope

    def get_sign_url(self, envelope, recipient, return_url):
        """
        Don't communicate with DocuSign when running tests.
        """
        return 'http://signing-service.com/send-user-here'

    def send_signed_document(self, envelope_id, user):
        """Mock method to send a signed DocuSign document to the user's email."""
        pass


class MockRecipient(object):
    def __init__(self):
        self.recipients = None
        self.envelopeId = None


def update_repository_provider(installation_id, github_repository_id, change_request_id):
    """Helper method to notify the repository provider of successful signature."""
    repo_service = cla.utils.get_repository_service('github')
    repo_service.update_change_request(installation_id, github_repository_id, change_request_id)


def get_org_from_return_url(repo_provider_type, return_url, orgs):
    """
    Helper method to find specific org from list of orgs under same contract group
    This is a hack solution since it totally depends on return_url and repo service provider
    However, based on the current implementation, it's a simple way to invovled minimal refactor
    BTW, I don't believe the last team can do a successful demo without doing any tweaks like this

    :param repo_provider_type: The repo service provider.
    :type repo_provider_type: string
    :param return_url: The URL will be redirected after signature done.
    :type return_url: string
    :return: List of Organizations of any repo service provider.
    :rtype: [any_repo_service_provider.Organization]
    """
    if repo_provider_type == 'github':
        split_url = return_url.split('/')  # parse repo name from URL
        target_org_name = split_url[3]
        for org in orgs:
            if org.get_organization_name() == target_org_name:
                return org
        raise Exception('Not found org: {} under current CLA project'.format(target_org_name))
    else:
        raise Exception('Repo service: {} not supported'.format(repo_provider_type))


def get_docusign_tabs_from_document(document: Document,
                                    document_id: int,
                                    default_values: Optional[Dict[str, Any]] = None):
    """
    Helper function to extract the DocuSign tabs out of a document object.

    :param document: The document to extract the tabs from.
    :type document: cla.models.model_interfaces.Document
    :param document_id: The ID of the document to use for grouping of the tabs.
    :type document_id: int
    :return: List of formatted tabs for consumption by pydocusign.
    :rtype: [pydocusign.Tab]
    """
    tabs = []
    for tab in document.get_document_tabs():
        args = {
            'documentId': document_id,
            'pageNumber': tab.get_document_tab_page(),
            'xPosition': tab.get_document_tab_position_x(),
            'yPosition': tab.get_document_tab_position_y(),
            'width': tab.get_document_tab_width(),
            'height': tab.get_document_tab_height(),
            'customTabId': tab.get_document_tab_id(),
            'tabLabel': tab.get_document_tab_id(),
            'name': tab.get_document_tab_name()
        }

        if tab.get_document_tab_anchor_string() is not None:
            # Set only when anchor string exists 
            args['anchorString'] = tab.get_document_tab_anchor_string()
            args['anchorIgnoreIfNotPresent'] = tab.get_document_tab_anchor_ignore_if_not_present()
            args['anchorXOffset'] = tab.get_document_tab_anchor_x_offset()
            args['anchorYOffset'] = tab.get_document_tab_anchor_y_offset()
            # Remove x,y coordinates since offsets will define them
        # del args['xPosition']
        # del args['yPosition']

        if default_values is not None and \
                default_values.get(tab.get_document_tab_id()) is not None:
            args['value'] = default_values[tab.get_document_tab_id()]

        tab_type = tab.get_document_tab_type()
        if tab_type == 'text':
            tab_class = pydocusign.TextTab
        elif tab_type == 'text_unlocked':
            tab_class = TextUnlockedTab
            args['locked'] = False
        elif tab_type == 'text_optional':
            tab_class = TextOptionalTab
            args['required'] = False
        elif tab_type == 'number':
            tab_class = pydocusign.NumberTab
        elif tab_type == 'sign':
            tab_class = pydocusign.SignHereTab
        elif tab_type == 'date':
            tab_class = pydocusign.DateSignedTab
        else:
            cla.log.warning('Invalid tab type specified (%s) in document file ID %s',
                            tab_type, document.get_document_file_id())
            continue

        tab_obj = tab_class(**args)
        tabs.append(tab_obj)

    return tabs


def populate_signature_from_icla_callback(content: str, icla_tree: ET, signature: Signature):
    """
    Populates the signature instance from the given xml payload from docusign icla
    :param content: the raw xml
    :param icla_tree:
    :param signature:
    :return:
    """
    user_docusign_date_signed = icla_tree.find('.//' + DocuSign.TAGS['agreement_date'])
    if user_docusign_date_signed is None:
        user_docusign_date_signed = icla_tree.find('.//' + DocuSign.TAGS['signed_date'])

    if user_docusign_date_signed is not None:
        user_docusign_date_signed = user_docusign_date_signed.text
        cla.log.debug(f"setting user_docusign_date_signed attribute : {user_docusign_date_signed}")
        signature.set_user_docusign_date_signed(user_docusign_date_signed)

    full_name_field = icla_tree.find(".//*[@name='full_name']")
    # If full_name not found, try looking for the signatory_name
    if full_name_field is None:
        full_name_field = icla_tree.find(".//*[@name='signatory_name']")

    # If we found it...
    if full_name_field is not None:
        full_name = full_name_field.find(DocuSign.TAGS['field_value'])
        if full_name is not None:
            full_name = full_name.text
            cla.log.debug(f"setting user_docusign_name attribute : {full_name}")
            signature.set_user_docusign_name(full_name)

    # seems the content could be bytes
    if hasattr(content, "decode"):
        content = content.decode("utf-8")
    else:
        content = str(content)

    signature.set_user_docusign_raw_xml(content)


def populate_signature_from_ccla_callback(content: str, ccla_tree: ET, signature: Signature):
    """
    Populates the signature instance from the given xml payload from docusign ccla
    :param content:
    :param ccla_tree:
    :param signature:
    :return:
    """
    user_docusign_date_signed = ccla_tree.find('.//' + DocuSign.TAGS['agreement_date'])
    if user_docusign_date_signed is None:
        user_docusign_date_signed = ccla_tree.find('.//' + DocuSign.TAGS['signed_date'])

    if user_docusign_date_signed is not None:
        user_docusign_date_signed = user_docusign_date_signed.text
        cla.log.debug(f"setting user_docusign_date_signed attribute : {user_docusign_date_signed}")
        signature.set_user_docusign_date_signed(user_docusign_date_signed)

    signatory_name_field = ccla_tree.find(".//*[@name='signatory_name']")
    signatory_name = signatory_name_field.find(DocuSign.TAGS['field_value'])
    if signatory_name is not None:
        signatory_name = signatory_name.text
        cla.log.debug(f"setting user_docusign_name attribute : {signatory_name}")
        signature.set_user_docusign_name(signatory_name)

    # seems the content could be bytes
    if hasattr(content, "decode"):
        content = content.decode("utf-8")
    else:
        content = str(content)
    signature.set_user_docusign_raw_xml(content)


# Returns a dictionary of document id to value
def create_default_company_values(company: Company,
                                  signatory_name: str,
                                  signatory_email: str,
                                  manager_name: str,
                                  manager_email: str,
                                  schedule_a: str) -> Dict[str, Any]:
    values = {}

    if company is not None:
        if company.get_company_name() is not None:
            values['corporation_name'] = company.get_company_name()
            values['corporation'] = company.get_company_name()
        if company.get_signing_entity_name() is not None:
            values["signing_entity_name"] = company.get_signing_entity_name()

    if signatory_name is not None:
        values['signatory_name'] = signatory_name

    if signatory_email is not None:
        values['signatory_email'] = signatory_email

    if manager_name is not None:
        values['point_of_contact'] = manager_name
        values['cla_manager_name'] = manager_name

    if manager_email is not None:
        values['email'] = manager_email
        values['cla_manager_email'] = manager_email

    if schedule_a is not None:
        values['scheduleA'] = schedule_a

    return values


def create_default_individual_values(user: User, preferred_email: str = None) -> Dict[str, Any]:
    values = {}

    if user is None:
        return values

    if user.get_user_name() is not None:
        values['full_name'] = user.get_user_name()
        values['public_name'] = user.get_user_name()

    if user.get_user_email(preferred_email=preferred_email) is not None:
        values['email'] = user.get_user_email()

    return values


class TextOptionalTab(pydocusign.Tab):
    """Tab to show a free-form text field on the document.
    """
    attributes = pydocusign.Tab._common_attributes + pydocusign.Tab._formatting_attributes + [
        'name',
        'value',
        'height',
        'width',
        'locked',
        'required'
    ]
    tabs_name = 'textTabs'


class TextUnlockedTab(pydocusign.Tab):
    """Tab to show a free-form text field on the document.
    """
    attributes = pydocusign.Tab._common_attributes + pydocusign.Tab._formatting_attributes + [
        'name',
        'value',
        'height',
        'width',
        'locked'
    ]
    tabs_name = 'textTabs'


# managers and contributors are tuples of (name, email)
def generate_manager_and_contributor_list(managers, contributors=None):
    lines = []

    for manager in managers:
        lines.append('CLA Manager: {}, {}'.format(manager[0], manager[1]))

    if contributors is not None:
        for contributor in contributors:
            lines.append('{}, {}'.format(contributor[0], contributor[1]))

    lines = '\n'.join([str(line) for line in lines])

    return lines
