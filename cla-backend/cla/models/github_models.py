# Copyright The Linux Foundation and each contributor to CommunityBridge.
# SPDX-License-Identifier: MIT

"""
Holds the GitHub repository service.
"""
import json
import os
import uuid
from typing import List, Union, Optional

import falcon
import github
from github import PullRequest
from github.GithubException import UnknownObjectException, BadCredentialsException, GithubException
from requests_oauthlib import OAuth2Session

import cla
from cla.controllers.github_application import GitHubInstallation
from cla.models import repository_service_interface, DoesNotExist
from cla.models.dynamo_models import Repository, GitHubOrg
from cla.utils import get_project_instance


class GitHub(repository_service_interface.RepositoryService):
    """
    The GitHub repository service.
    """

    def __init__(self):
        self.client = None

    def initialize(self, config):
        # username = config['GITHUB_USERNAME']
        # token = config['GITHUB_TOKEN']
        # self.client = self._get_github_client(username, token)
        pass

    def _get_github_client(self, username, token):  # pylint: disable=no-self-use
        return github.Github(username, token)

    def get_repository_id(self, repo_name, installation_id=None):
        """
        Helper method to get a GitHub repository ID based on repository name.

        :param repo_name: The name of the repository, example: 'linuxfoundation/cla'.
        :type repo_name: string
        :param installation_id: The github installation id
        :type installation_id: string
        :return: The repository ID.
        :rtype: integer
        """
        if installation_id is not None:
            self.client = get_github_integration_client(installation_id)
        try:
            return self.client.get_repo(repo_name).id
        except github.GithubException as err:
            cla.log.error('Could not find GitHub repository (%s), ensure it exists and that '
                          'your personal access token is configured with the repo scope', repo_name)
        except Exception as err:
            cla.log.error('Unknown error while getting GitHub repository ID for repository %s: %s',
                          repo_name, str(err))

    def received_activity(self, data):
        cla.log.debug('github_models.received_activity - Received GitHub activity: %s', data)
        if 'pull_request' not in data:
            cla.log.debug('github_models.received_activity - Activity not related to pull request - ignoring')
            return {'message': 'Not a pull request - no action performed'}
        if data['action'] == 'opened':
            cla.log.debug('github_models.received_activity - Handling opened pull request')
            return self.process_opened_pull_request(data)
        elif data['action'] == 'reopened':
            cla.log.debug('github_models.received_activity - Handling reopened pull request')
            return self.process_reopened_pull_request(data)
        elif data['action'] == 'closed':
            cla.log.debug('github_models.received_activity - Handling closed pull request')
            return self.process_closed_pull_request(data)
        elif data['action'] == 'synchronize':
            cla.log.debug('github_models.received_activity - Handling synchronized pull request')
            return self.process_synchronized_pull_request(data)
        else:
            cla.log.debug('github_models.received_activity - Ignoring unsupported action: {}'.format(data['action']))

    def sign_request(self, installation_id, github_repository_id, change_request_id, request):
        """
        This method gets called when the OAuth2 app (NOT the GitHub App) needs to get info on the
        user trying to sign. In this case we begin an OAuth2 exchange with the 'user:email' scope.
        """
        fn = 'sign_request'  # function name
        cla.log.debug(f'{fn} - Initiating GitHub sign request for installation_id: {installation_id}, '
                      f'for repository {github_repository_id}, '
                      f'for PR: {change_request_id}')
        # Not sure if we need a different token for each installation ID...
        cla.log.debug(f'{fn} - Loading session from request: {request}...')
        session = self._get_request_session(request)
        cla.log.debug(f'{fn} - Adding github details to session...')
        session['github_installation_id'] = installation_id
        session['github_repository_id'] = github_repository_id
        session['github_change_request_id'] = change_request_id

        cla.log.debug(f'{fn} - Determining return URL from the inbound request...')
        origin_url = self.get_return_url(github_repository_id, change_request_id, installation_id)
        cla.log.debug(f'{fn} - Return URL from the inbound request is {origin_url}...')
        session['github_origin_url'] = origin_url
        if 'github_oauth2_token' in session:
            cla.log.debug(f'{fn} - Using existing session GitHub OAuth2 token')
            return self.redirect_to_console(
                installation_id, github_repository_id, change_request_id,
                origin_url, request)
        else:
            cla.log.debug(f'{fn} - No existing GitHub OAuth2 token - building authorization url and state')
            authorization_url, state = self.get_authorization_url_and_state(installation_id,
                                                                            github_repository_id,
                                                                            int(change_request_id),
                                                                            ['user:email'])
            cla.log.debug(f'{fn} - Obtained GitHub OAuth2 state from authorization')
            session['github_oauth2_state'] = state
            cla.log.debug(f'{fn} - GitHub OAuth2 request with state {state} - sending user to {authorization_url}')
            raise falcon.HTTPFound(authorization_url)

    def _get_request_session(self, request):  # pylint: disable=no-self-use
        """
        Mockable method used to get the current user session.
        """
        # return request.context['session']
        session = request.context.get('session')
        if session is None:
            cla.log.warning(f'Session is empty for request: {request}')
        return session

    def get_authorization_url_and_state(self, installation_id, github_repository_id, pull_request_number, scope):
        """
        Helper method to get the GitHub OAuth2 authorization URL and state.

        This will be used to get the user's emails from GitHub.

        :TODO: Update comments.

        :param repository_id: The ID of the repository this request was initiated in.
        :type repository_id: int
        :param pull_request_number: The PR number this request was generated in.
        :type pull_request_number: int
        :param scope: The list of OAuth2 scopes to request from GitHub.
        :type scope: [string]
        """
        # Get the PR's html_url property.
        # origin = self.get_return_url(github_repository_id, pull_request_number, installation_id)
        # Add origin to user's session here?
        fn = 'get_authorization_url_and_state'
        api_base_url = os.environ.get('CLA_API_BASE', '')
        cla.log.debug(f'{fn} - Directing user to authorization: {os.path.join(api_base_url, "v2/github/installation")}')
        return self._get_authorization_url_and_state(os.environ['GH_OAUTH_CLIENT_ID'],
                                                     os.path.join(api_base_url, 'v2/github/installation'),
                                                     scope,
                                                     cla.conf['GITHUB_OAUTH_AUTHORIZE_URL'])

    def _get_authorization_url_and_state(self, client_id, redirect_uri, scope,
                                         authorize_url):  # pylint: disable=no-self-use
        """
        Mockable helper method to do the fetching of the authorization URL and state from GitHub.
        """
        return cla.utils.get_authorization_url_and_state(client_id, redirect_uri, scope, authorize_url)

    def oauth2_redirect(self, state, code, request):  # pylint: disable=too-many-arguments
        """
        This is where the user will end up after having authorized the CLA system
        to get information such as email address.

        It will handle storing the OAuth2 session information for this user for
        further requests and initiate the signing workflow.
        """
        cla.log.debug(f'Handling GitHub OAuth2 redirect with request: {dir(request)}')
        # TODO: should we load the session from the DynamoDB session table based on the 'state' value?
        session = self._get_request_session(request)  # request.context['session']
        cla.log.debug(f'State: {state}, Code: {code}, Session: {session}')

        if 'github_oauth2_state' in session:
            session_state = session['github_oauth2_state']
        else:
            session_state = None
            cla.log.warning('github_oauth2_state not set in session')

        if state != session_state:
            cla.log.warning('Invalid GitHub OAuth2 state %s expecting %s',
                            session_state, state)
            raise falcon.HTTPBadRequest('Invalid OAuth2 state', state)

        # Get session information for this request.
        cla.log.debug('Attempting to fetch OAuth2 token for state %s', state)
        installation_id = session.get('github_installation_id', None)
        github_repository_id = session.get('github_repository_id', None)
        change_request_id = session.get('github_change_request_id', None)
        origin_url = session.get('github_origin_url', None)
        state = session.get('github_oauth2_state')
        token_url = cla.conf['GITHUB_OAUTH_TOKEN_URL']
        client_id = os.environ['GH_OAUTH_CLIENT_ID']
        client_secret = os.environ['GH_OAUTH_SECRET']
        cla.log.debug('fetching token...')
        token = self._fetch_token(client_id, state, token_url, client_secret, code)
        cla.log.debug(f'OAuth2 token received for state {state}: {token} - storing token in session')
        session['github_oauth2_token'] = token
        cla.log.debug(f'Redirecting the user back to the console...')
        return self.redirect_to_console(installation_id, github_repository_id, change_request_id, origin_url, request)

    def redirect_to_console(self, installation_id, repository_id, pull_request_id, redirect, request):
        fn = 'redirect_to_console'
        console_endpoint = cla.conf['CONTRIBUTOR_BASE_URL']
        console_v2_endpoint = cla.conf['CONTRIBUTOR_V2_BASE_URL']
        # Get repository using github's repository ID.
        repository = Repository().get_repository_by_external_id(repository_id, "github")
        if repository is None:
            cla.log.warning(f'{fn} - Could not find repository with the following '
                            f'repository_id: {repository_id}')
            return None

        # Get project ID from this repository
        project_id = repository.get_repository_project_id()

        try:
            project = get_project_instance()
            project.load(str(project_id))
        except DoesNotExist as err:
            return {'errors': {'project_id': str(err)}}

        user = self.get_or_create_user(request)
        # Ensure user actually requires a signature for this project.
        # TODO: Skipping this for now - we can do this for ICLAs but there's no easy way of doing
        # the check for CCLAs as we need to know in advance what the company_id is that we're checking
        # the CCLA signature for.
        # We'll have to create a function that fetches the latest CCLA regardless of company_id.
        # icla_signature = cla.utils.get_user_signature_by_github_repository(installation_id, user)
        # ccla_signature = cla.utils.get_user_signature_by_github_repository(installation_id, user, company_id=?)
        # try:
        # document = cla.utils.get_project_latest_individual_document(project_id)
        # except DoesNotExist:
        # cla.log.debug('No ICLA for project %s' %project_id)
        # if signature is not None and \
        # signature.get_signature_document_major_version() == document.get_document_major_version():
        # return cla.utils.redirect_user_by_signature(user, signature)
        # Store repository and PR info so we can redirect the user back later.
        cla.utils.set_active_signature_metadata(user.get_user_id(), project_id, repository_id, pull_request_id)

        console_url = ''

        # Temporary condition until all CLA Groups are ready for the v2 Contributor Console
        if project.get_version() == 'v2':
            # Generate url for the v2 console
            console_url = 'https://' + console_v2_endpoint + \
                          '/#/cla/project/' + project_id + \
                          '/user/' + user.get_user_id() + \
                          '?redirect=' + redirect
            cla.log.debug(f'{fn} - redirecting to v2 console: {console_url}...')
        else:
            # Generate url for the v1 contributor console
            console_url = 'https://' + console_endpoint + \
                          '/#/cla/project/' + project_id + \
                          '/user/' + user.get_user_id() + \
                          '?redirect=' + redirect
            cla.log.debug(f'{fn} - redirecting to v1 console: {console_url}...')

        raise falcon.HTTPFound(console_url)

    def _fetch_token(self, client_id, state, token_url, client_secret,
                     code):  # pylint: disable=too-many-arguments,no-self-use
        """
        Mockable method to fetch a OAuth2Session token.
        """
        return cla.utils.fetch_token(client_id, state, token_url, client_secret, code)

    def sign_workflow(self, installation_id, github_repository_id, pull_request_number, request):
        """
        Once we have the 'github_oauth2_token' value in the user's session, we can initiate the
        signing workflow.
        """
        fn = 'sign_workflow'
        cla.log.warning(f'{fn} - Initiating GitHub signing workflow for '
                        f'GitHub repo {github_repository_id} '
                        f'with PR: {pull_request_number}')
        user = self.get_or_create_user(request)
        signature = cla.utils.get_user_signature_by_github_repository(installation_id, user)
        project_id = cla.utils.get_project_id_from_installation_id(installation_id)
        document = cla.utils.get_project_latest_individual_document(project_id)
        if signature is not None and \
                signature.get_signature_document_major_version() == document.get_document_major_version():
            return cla.utils.redirect_user_by_signature(user, signature)
        else:
            # Signature not found or older version, create new one and send user to sign.
            cla.utils.request_individual_signature(installation_id, github_repository_id, user, pull_request_number)

    def process_opened_pull_request(self, data):
        """
        Helper method to handle a webhook fired from GitHub for an opened PR.

        :param data: The data returned from GitHub on this webhook.
        :type data: dict
        """
        pull_request_id = data['pull_request']['number']
        github_repository_id = data['repository']['id']
        installation_id = data['installation']['id']
        self.update_change_request(installation_id, github_repository_id, pull_request_id)

    def process_easycla_command_comment(self, data):
        """
        Processes easycla command comment if present
        :param data: github issue comment webhook event payload : https://docs.github.com/en/free-pro-team@latest/developers/webhooks-and-events/webhook-events-and-payloads#issue_comment
        :return:
        """
        comment_str = data.get("comment", {}).get("body", "")
        if not comment_str:
            raise ValueError("missing comment body, ignoring the message")

        if "/easycla" not in comment_str.split():
            raise ValueError("unsupported comment supplied, currently only /easycla command is supported")

        github_repository_id = data.get('repository', {}).get('id', None)
        if not github_repository_id:
            raise ValueError("missing github repository id in pull request comment")
        cla.log.debug(f"comment trigger for github_repo : {github_repository_id}")

        # turns out pull request id and issue is the same thing
        pull_request_id = data.get("issue", {}).get("number", None)
        if not pull_request_id:
            raise ValueError("missing pull request id ")
        cla.log.debug(f"comment trigger for pull_request_id : {pull_request_id}")

        cla.log.debug("installation object : ", data.get('installation', {}))
        installation_id = data.get('installation', {}).get('id', None)
        if not installation_id:
            raise ValueError("missing installation id in pull request comment")
        cla.log.debug(f"comment trigger for installation_id : {installation_id}")

        self.update_change_request(installation_id, github_repository_id, pull_request_id)

    def get_return_url(self, github_repository_id, change_request_id, installation_id):
        pull_request = self.get_pull_request(github_repository_id, change_request_id, installation_id)
        return pull_request.html_url

    def update_change_request(self, installation_id, github_repository_id, change_request_id):
        fn = 'update_change_request'
        # Queries GH for the complete pull request details, see:
        # https://developer.github.com/v3/pulls/#response-1
        try:
            # check if change_request_id is a valid int
            _ = int(change_request_id)
            pull_request = self.get_pull_request(github_repository_id, change_request_id, installation_id)
        except ValueError:
            cla.log.error(f'{fn} - Invalid PR: {change_request_id} . (Unable to cast to integer) ')
            return
        cla.log.debug(f'{fn} - retrieved pull request: {pull_request}')

        # Get all unique users/authors involved in this PR - returns a list of
        # (commit_sha_string, (author_id, author_username, author_email) tuples
        commit_authors = get_pull_request_commit_authors(pull_request)

        try:
            # Get existing repository info using the repository's external ID,
            # which is the repository ID assigned by github.
            cla.log.debug(f'{fn} - PR: {pull_request.number}, Loading GitHub repository by id: {github_repository_id}')
            repository = Repository().get_repository_by_external_id(github_repository_id, "github")
            if repository is None:
                cla.log.warning(f'{fn} - PR: {pull_request.number}, Failed to load GitHub repository by '
                                f'id: {github_repository_id} in our DB - repository reference is None - '
                                'Is this org/repo configured in the Project Console?'
                                ' Unable to update status.')
                return
        except DoesNotExist:
            cla.log.warning(f'{fn} - PR: {pull_request.number}, could not find repository with the '
                            f'repository ID: {github_repository_id}')
            cla.log.warning(f'{fn} - PR: {pull_request.number}, failed to update change request of '
                            f'repository {github_repository_id} - returning')
            return

        # Get Github Organization name that the repository is configured to.
        organization_name = repository.get_repository_organization_name()
        cla.log.debug(f'{fn} - PR: {pull_request.number}, determined github organization is: {organization_name}')

        # Check that the Github Organization exists.
        github_org = GitHubOrg()
        try:
            github_org.load(organization_name)
        except DoesNotExist:
            cla.log.warning(f'{fn} - PR: {pull_request.number}, Could not find Github Organization '
                            f'with the following organization name: {organization_name}')
            cla.log.warning(f'{fn}- PR: {pull_request.number}, Failed to update change request of '
                            f'repository {github_repository_id} - returning')
            return

            # Ensure that installation ID for this organization matches the given installation ID
        if github_org.get_organization_installation_id() != installation_id:
            cla.log.warning(f'{fn} - PR: {pull_request.number}, '
                            f'the installation ID: {github_org.get_organization_installation_id()} '
                            f'of this organization does not match installation ID: {installation_id} '
                            'given by the pull request.')
            cla.log.error(f'{fn} - PR: {pull_request.number}, Failed to update change request '
                          f'of repository {github_repository_id} - returning')
            return

        # Retrieve project ID from the repository.
        project_id = repository.get_repository_project_id()
        project = get_project_instance()
        project.load(str(project_id))

        # Find users who have signed and who have not signed.
        signed = []
        missing = []

        cla.log.debug(f'{fn} - PR: {pull_request.number}, scanning users - '
                      'determining who has signed a CLA an who has not.')
        for commit_sha, author_info in commit_authors:
            # Extract the author info tuple details
            author_id = author_info[0]
            author_username = author_info[1]
            author_email = author_info[2]
            cla.log.debug(f'{fn} - PR: {pull_request.number}, '
                          f'processing sha: {commit_sha} '
                          f'from author id: {author_id}, username: {author_username}, email: {author_email}')
            handle_commit_from_user(project, commit_sha, author_info, signed, missing)

        cla.log.debug(f'{fn} - PR: {pull_request.number}, '
                      f'updating github pull request for repo: {github_repository_id}, '
                      f'with signed authors: {signed} '
                      f'with missing authors: {missing}')
        repository_name = repository.get_repository_name()
        update_pull_request(installation_id, github_repository_id, pull_request, repository_name,
                            signed=signed, missing=missing)

    def get_pull_request(self, github_repository_id, pull_request_number, installation_id):
        """
        Helper method to get the pull request object from GitHub.

        :param github_repository_id: The ID of the GitHub repository.
        :type github_repository_id: int
        :param pull_request_number: The number (not ID) of the GitHub PR.
        :type pull_request_number: int
        :param installation_id: The ID of the GitHub application installed on this repository.
        :type installation_id: int | None
        """
        cla.log.debug('Getting PR %s from GitHub repository %s', pull_request_number, github_repository_id)
        if self.client is None:
            self.client = get_github_integration_client(installation_id)
        repo = self.client.get_repo(int(github_repository_id))
        try:
            return repo.get_pull(int(pull_request_number))
        except UnknownObjectException:
            cla.log.error('Could not find pull request %s for repository %s - ensure it '
                          'exists and that your personal access token has the "repo" scope enabled',
                          pull_request_number, github_repository_id)
        except BadCredentialsException as err:
            cla.log.error('Invalid GitHub credentials provided: %s', str(err))

    def get_or_create_user(self, request):
        """
        Helper method to either get or create a user based on the GitHub request made.

        :param request: The hug request object for this API call.
        :type request: Request
        """
        session = self._get_request_session(request)
        github_user = self.get_user_data(session, os.environ['GH_OAUTH_CLIENT_ID'])
        if 'error' in github_user:
            # Could not get GitHub user data - maybe user revoked CLA app permissions?
            session = self._get_request_session(request)
            del session['github_oauth2_state']
            del session['github_oauth2_token']
            cla.log.warning('Deleted OAuth2 session data - retrying token exchange next time')
            raise falcon.HTTPError('400 Bad Request', 'github_oauth2_token',
                                   'Token permissions have been rejected, please try again')

        emails = self.get_user_emails(session, os.environ['GH_OAUTH_CLIENT_ID'])
        if len(emails) < 1:
            cla.log.warning('GitHub user has no verified email address: %s (%s)',
                            github_user['name'], github_user['login'])
            raise falcon.HTTPError(
                '412 Precondition Failed', 'email',
                'Please verify at least one email address with GitHub')

        cla.log.debug('Trying to load GitHub user by GitHub ID: %s', github_user['id'])
        users = cla.utils.get_user_instance().get_user_by_github_id(github_user['id'])
        if users is not None:
            # Users search can return more than one match - so it's an array - we set the first record value for now??
            user = users[0]
            cla.log.debug('Loaded GitHub user by GitHub ID: %s - %s (%s)',
                          user.get_user_name(),
                          user.get_user_emails(),
                          user.get_user_github_id())

            # update/set the github username if available
            cla.utils.update_github_username(github_user, user)

            user.set_user_emails(emails)
            user.save()
            return user

        # User not found by GitHub ID, trying by email.
        cla.log.debug('Could not find GitHub user by GitHub ID: %s', github_user['id'])
        # TODO: This is very slow and needs to be improved - may need a DB schema change.
        users = None
        user = cla.utils.get_user_instance()
        for email in emails:
            users = user.get_user_by_email(email)
            if users is not None:
                break

        if users is not None:
            # Users search can return more than one match - so it's an array - we set the first record value for now??
            user = users[0]
            # Found user by email, setting the GitHub ID
            user.set_user_github_id(github_user['id'])

            # update/set the github username if available
            cla.utils.update_github_username(github_user, user)

            user.set_user_emails(emails)
            user.save()
            cla.log.debug(f'Loaded GitHub user by email: {user}')
            return user

        # User not found, create.
        cla.log.debug(f'Could not find GitHub user by email: {emails}')
        cla.log.debug(f'Creating new GitHub user {github_user["name"]} - '
                      f'({github_user["id"]}/{github_user["login"]}), '
                      f'emails: {emails}')
        user = cla.utils.get_user_instance()
        user.set_user_id(str(uuid.uuid4()))
        user.set_user_emails(emails)
        user.set_user_name(github_user['name'])
        user.set_user_github_id(github_user['id'])
        user.set_user_github_username(github_user['login'])
        user.save()
        return user

    def get_user_data(self, session, client_id):  # pylint: disable=no-self-use
        """
        Mockable method to get user data. Returns all GitHub user data we have
        on the user based on the current OAuth2 session.

        :param session: The current user session.
        :type session: dict
        :param client_id: The GitHub OAuth2 client ID.
        :type client_id: string
        """
        token = session['github_oauth2_token']
        oauth2 = OAuth2Session(client_id, token=token)
        request = oauth2.get('https://api.github.com/user')
        github_user = request.json()
        cla.log.debug('GitHub user data: %s', github_user)
        if 'message' in github_user:
            cla.log.error('Could not get user data with OAuth2 token: %s', github_user['message'])
            return {'error': 'Could not get user data: %s' % github_user['message']}
        return github_user

    def get_user_emails(self, session, client_id) -> Union[List[str], dict]:  # pylint: disable=no-self-use
        """
        Mockable method to get all user emails based on OAuth2 session.

        :param session: The current user session.
        :type session: dict
        :param client_id: The GitHub OAuth2 client ID.
        :type client_id: string
        """
        emails = self._fetch_github_emails(session=session, client_id=client_id)
        cla.log.debug('GitHub user emails: %s', emails)
        if 'error' in emails:
            return emails
        return [item['email'] for item in emails if item['verified']]

    def get_primary_user_email(self, request) -> Union[Optional[str], dict]:
        """
        gets the user primary email from the registered emails from the github api
        """
        fn = 'github_models.get_primary_user_email'
        try:
            cla.log.debug(f'{fn} - Fetching Github primary email')
            session = self._get_request_session(request)
            client_id = os.environ['GH_OAUTH_CLIENT_ID']
            emails = self._fetch_github_emails(session=session, client_id=client_id)
            if "error" in emails:
                return None

            for email in emails:
                if email.get("verified", False) and email.get("primary", False):
                    return email["email"]
        except Exception as e:
            cla.log.warning(f'{fn} - lookup failed - {e} - returning None')
            return None
        return None

    def _fetch_github_emails(self, session, client_id) -> Union[List[dict], dict]:
        """
        Method is responsible for fetching the user emails from /user/emails endpoint
        :param session:
        :param client_id:
        :return:
        """
        fn = 'github_models._fetch_github_emails'  # function name
        # Use the user's token to fetch their public email(s) - don't use the system token as this endpoint won't work
        # as expected
        token = session.get('github_oauth2_token')
        if token is None:
            cla.log.warning(f'{fn} - unable to load github_oauth2_token from the session - session is empty')
        oauth2 = OAuth2Session(client_id, token=token)
        request = oauth2.get('https://api.github.com/user/emails')
        resp = request.json()
        if 'message' in resp:
            cla.log.warning(f'{fn} - could not get user emails with OAuth2 token: {resp["message"]}')
            return {'error': 'Could not get user emails: %s' % resp['message']}
        return resp

    def process_reopened_pull_request(self, data):
        """
        Helper method to process a re-opened GitHub PR.

        Simply calls the self.process_opened_pull_request() method with the data provided.

        :param data: The data provided by the GitHub webhook.
        :type data: dict
        """
        return self.process_opened_pull_request(data)

    def process_closed_pull_request(self, data):
        """
        Helper method to process a closed GitHub PR.

        :param data: The data provided by the GitHub webhook.
        :type data: dict
        """
        pass

    def process_synchronized_pull_request(self, data):
        """
        Helper method to process a synchronized GitHub PR.

        Should be called when a new commit comes through on the PR.
        Simply calls the self.process_opened_pull_request() method with the data provided.
        This should re-check all commits for author information.

        :param data: The data provided by the GitHub webhook.
        :type data: dict
        """
        return self.process_opened_pull_request(data)


def create_repository(data):
    """
    Helper method to create a repository object in the CLA database given PR data.

    :param data: The data provided by the GitHub webhook.
    :type data: dict
    :return: The newly created repository object - already in the DB.
    :rtype: cla.models.model_interfaces.Repository
    """
    try:
        repository = cla.utils.get_repository_instance()
        repository.set_repository_id(str(uuid.uuid4()))
        # TODO: Need to use an ID unique across all repository providers instead of namespace.
        full_name = data['repository']['full_name']
        namespace = full_name.split('/')[0]
        repository.set_repository_project_id(namespace)
        repository.set_repository_external_id(data['repository']['id'])
        repository.set_repository_name(full_name)
        repository.set_repository_type('github')
        repository.set_repository_url(data['repository']['html_url'])
        repository.save()
        return repository
    except Exception as err:
        cla.log.warning('Could not create GitHub repository automatically: %s', str(err))
        return None


def handle_commit_from_user(project, commit_sha, author_info, signed, missing):  # pylint: disable=too-many-arguments
    """
    Helper method to triage commits between signed and not-signed user signatures.

    :param project: The project model for this github PR organization.
    :type project: Project
    :param commit_sha: Commit has as a string
    :type commit_sha: string
    :param author_info: the commit author details, including id, name, email (if available)
    :type author_info: tuple of (author_id, author_username, author_email)
    :param signed: Reference to a list of signed authors so far. Should be modified
      in-place to add a signer if found.
    :type signed: list of strings
    :param missing: Reference to a list of authors who have not signed yet.
        Should be modified in-place to add a missing signer if found.
    :type missing: list of strings
    """

    # Extract the author_info tuple details
    author_id = author_info[0]
    author_username = author_info[1]
    author_email = author_info[2]
    cla.log.debug(f'Looking up GitHub user (author_id: {author_id}, '
                  f'author_username: {author_username}, '
                  f'auth_email: {author_email})')

    # attempt to lookup the user in our database by GH id -
    # may return multiple users that match this author_id
    users = cla.utils.get_user_instance().get_user_by_github_id(author_id)
    if users is None:
        # GitHub user not in system yet, signature does not exist for this user.
        cla.log.debug(f'GitHub user (id: {author_id}, '
                      f'user: {author_username}, '
                      f'email: {author_email}) lookup by github id not found in our database, '
                      'attempting to looking up user by email...')

        # Try looking up user by email as a fallback
        users = cla.utils.get_user_instance().get_user_by_email(author_email)

        # Got one or more records by searching the email
        if users is not None:
            cla.log.debug(f'Found {len(users)} GitHub user(s) matching github email: {author_email}')
            for user in users:
                cla.log.debug(f'GitHub user found in our database: {user}')

                # For now, accept non-github users as legitimate users.
                # Does this user have a signed signature for this project? If so, add to the signed list and return,
                # no reason to continue looking
                if cla.utils.user_signed_project_signature(user, project):
                    signed.append((commit_sha, author_username))
                    return

            # Didn't find a signed signature for this project - add to our missing bucket list
            # author_info consists of: [author_id, author_username, author_email]
            missing.append((commit_sha, list(author_info)))
        else:
            # Not seen this user before - no record on file in our user's database
            cla.log.debug(f'GitHub user (id: {author_id}, '
                          f'user: {author_username}, '
                          f'email: {author_email}) lookup by email in our database failed - not found')

            # This bit of logic below needs to be reconsidered - query logic takes a very long time for large
            # projects like CNCF which significantly delays updating the GH PR status.
            # Revisit once we add more indexes to the table

            # # Check to see if not found user is whitelisted to assist in triaging github comment
            # # Search for the CCLA signatures for this project - wish we had a company ID to restrict the query...
            # signatures = cla.utils.get_signature_instance().get_signatures_by_project(
            #     project.get_project_id(),
            #     signature_signed=True,
            #     signature_approved=True,
            #     signature_reference_type='company')
            #
            # list_author_info = list(author_info)
            # for signature in signatures:
            #     if cla.utils.is_whitelisted(
            #             signature,
            #             email=author_email,
            #             github_id=author_id,
            #             github_username=author_username
            #     ):
            #         # Append whitelisted flag to the author info list
            #         cla.log.debug(f'Github user(id:{author_id}, '
            #                       f'user: {author_username}, '
            #                       f'email {author_email}) is whitelisted but not a CLA user')
            #         list_author_info.append(True)
            #         break
            # missing.append((commit_sha, list_author_info))

            # For now - we'll just return the author info as a list without the flag to indicate that they have been on
            # the approved list for any company/signature
            # author_info consists of: [author_id, author_username, author_email]
            missing.append((commit_sha, list(author_info)))
    else:
        cla.log.debug(f'Found {len(users)} GitHub user(s) matching github id: {author_id} in our database')
        if len(users) > 1:
            cla.log.warning(f'more than 1 user found in our user database - user: {users} - '
                            f'will ONLY evaluate the first one')

        # Just review the first user that we were able to fetch from our DB
        user = users[0]
        cla.log.debug(f'GitHub user found in our database: {user}')

        # Does this user have a signed signature for this project? If so, add to the signed list and return,
        # no reason to continue looking
        if cla.utils.user_signed_project_signature(user, project):
            signed.append((commit_sha, author_username))
            return

        list_author_info = list(author_info)

        # If the user does not have a company ID assigned, then they have not been associated with a company as
        # part of the Contributor console workflow
        if user.get_user_company_id() is None:
            missing.append((commit_sha, list_author_info))
            return

        # Perform a specific search for the user's project + company + CCLA
        signatures = cla.utils.get_signature_instance().get_signatures_by_project(
            project_id=project.get_project_id(),
            signature_signed=True,
            signature_approved=True,
            signature_type='ccla',
            signature_reference_type='company',
            signature_reference_id=user.get_user_company_id(),
            signature_user_ccla_company_id=None,
        )

        # Should only return one signature record
        cla.log.debug(f'Found {len(signatures)} CCLA signatures for company: {user.get_user_company_id()}, '
                      f'project: {project.get_project_id()} in our database.')

        # Should never happen - warn if we see this
        if len(signatures) > 1:
            cla.log.warning(f'more than 1 CCLA signature record found in our database - signatures: {signatures}')

        for signature in signatures:
            if cla.utils.is_whitelisted(
                    signature,
                    email=author_email,
                    github_id=author_id,
                    github_username=author_username
            ):
                # Append whitelisted flag to the author info list
                cla.log.debug(f'Github user(id:{author_id}, '
                              f'user: {author_username}, '
                              f'email {author_email}) is on the approved list, '
                              'but not affiliated with a company')
                list_author_info.append(True)
                break
        missing.append((commit_sha, list_author_info))


def get_pull_request_commit_authors(pull_request):
    """
    Helper function to extract all committer information for a GitHub PR.

    For pull_request data model, see:
    https://developer.github.com/v3/pulls/
    For commits on a pull request, see:
    https://developer.github.com/v3/pulls/#list-commits-on-a-pull-request
    For activity callback, see:
    https://developer.github.com/v3/activity/events/types/#pullrequestevent

    :param pull_request: A GitHub pull request to examine.
    :type pull_request: GitHub.PullRequest
    :return: A list of tuples containing a tuple of (commit_sha_string, (author_id, author_username, author_email)) -
    the second item is another tuple of author info.
    :rtype: [(commit_sha_string, (author_id, author_username, author_email)]
    """
    cla.log.debug('Querying pull request commits for author information...')
    commit_authors = []
    for commit in pull_request.get_commits():
        cla.log.debug('Processing commit while looking for authors, commit: {}'.format(commit.sha))
        # Note: we can get the author info in two different ways:
        if commit.author is not None:
            # commit.author is a github.NamedUser.NamedUser type object
            # https://pygithub.readthedocs.io/en/latest/github_objects/NamedUser.html
            if commit.author.name is not None:
                cla.log.debug('PR: {}, GitHub commit.author.name author found for commit SHA {}, '
                              'author id: {}, name: {}, email: {}'.
                              format(pull_request.number, commit.sha, commit.author.id,
                                     commit.author.name, commit.author.email))
                commit_authors.append((commit.sha, (commit.author.id, commit.author.name, commit.author.email)))
            elif commit.author.login is not None:
                cla.log.debug('PR: {}, GitHub commit.author.login author found for commit SHA {}, '
                              'author id: {}, login: {}, email: {}'.
                              format(pull_request.number, commit.sha, commit.author.id,
                                     commit.author.login, commit.author.email))
                commit_authors.append((commit.sha, (commit.author.id, commit.author.login, commit.author.email)))
            else:
                cla.log.debug(f'PR: {pull_request.number}, GitHub commit.author.name and commit.author.login '
                              f'author information NOT found for commit SHA {commit.sha}, '
                              f'author id: {commit.author.id}, '
                              f'name: {commit.author.name}, '
                              f'login: {commit.author.login}, '
                              f'email: {commit.author.email}')
                commit_authors.append((commit.sha, None))
        elif commit.commit.author is not None:
            cla.log.debug('github.GitAuthor.GitAuthor object: {}'.format(commit.commit.author))
            # commit.commit.author is a github.GitAuthor.GitAuthor object type - object
            # only has date, name and email attributes - no ID attribute/value
            # https://pygithub.readthedocs.io/en/latest/github_objects/GitAuthor.html
            cla.log.debug('PR: {}, GitHub NamedUser author NOT found for commit SHA {}, '
                          'however, found GitAuthor author id: None, name: {}, email: {}'.
                          format(pull_request.number, commit.sha,
                                 commit.commit.author.name, commit.commit.author.email))
            commit_authors.append((commit.sha, (None, commit.commit.author.name, commit.commit.author.email)))
        else:
            cla.log.warning('PR: {}, could not find any commit author for SHA {}'.
                            format(pull_request.number, commit.sha))
            commit_authors.append((commit.sha, None))

    return commit_authors


def has_check_previously_failed(pull_request: PullRequest) -> bool:
    """
    Review the status updates in the PR. Identify 1 or more previous failed
    updates from the EasyCLA bot. If we fine one, return True, otherwise
    return False

    :param pull_request: the GitHub pull request object
    :return: True if the EasyCLA bot check previously failed, otherwise return False
    """
    comments = pull_request.get_issue_comments()
    # Look through all the comments
    for comment in comments:
        # Our bot comments include the following text
        # A previously failed check has 'not authorized' somewhere in the body
        if 'CLA Not Signed' in comment.body and 'not authorized' in comment.body:
            return True
        if 'CLA Confirmation Needed' in comment.body and 'must confirm their affiliation' in comment.body:
            return True
        if 'CLA Missing ID' in comment.body and 'is missing the User' in comment.body:
            return True
    return False


def update_pull_request(installation_id, github_repository_id, pull_request, repository_name, signed,
                        missing):  # pylint: disable=too-many-locals
    """
    Helper function to update a PR's comment and status based on the list of signers.

    :param installation_id: The ID of the GitHub installation
    :type installation_id: int
    :param github_repository_id: The ID of the GitHub repository this PR belongs to.
    :type github_repository_id: int
    :param pull_request: The GitHub PullRequest object for this PR.
    :type pull_request: GitHub.PullRequest
    :param repository_name: The GitHub repository name for this PR.
    :type repository_name: string
    :param signed: The list of (commit hash, author name) tuples that have signed an
        signature for this PR.
    :type signed: [(string, string)]
    :param missing: The list of (commit hash, author name) tuples that have not signed
        an signature for this PR.
    :type missing: [(string, list)]
    """
    notification = cla.conf['GITHUB_PR_NOTIFICATION']
    both = notification == 'status+comment' or notification == 'comment+status'
    last_commit = pull_request.get_commits().reversed[0]

    # Here we update the PR status by adding/updating the PR body - this is the way the EasyCLA app
    # knows if it is pass/fail.
    # Create check run for users that haven't yet signed and/or affiliated
    if missing:
        text = ""
        for authors in missing:
            # Check for valid github id
            if authors[1][0] is None:
                help_url = "https://help.github.com/en/github/committing-changes-to-your-project/why-are-my-commits-linked-to-the-wrong-user"
            else:
                help_url = cla.utils.get_full_sign_url('github', str(installation_id), github_repository_id,
                                                       pull_request.number)
            client = GitHubInstallation(installation_id)
            # check if unsigned user is whitelisted
            commit_sha = authors[0]
            if commit_sha != last_commit.sha:
                continue
            author_email = authors[1][2]
            author_id = authors[1][0]
            if author_id:
                if len(authors[1]) == 4:
                    text += f'{author_email} must confirm corporate affiliation.\n'
                else:
                    text += f'{author_email} is not authorized under a signed CLA.\n'
            else:
                text += f'{author_email} is not linked to this commit. \n'

        payload = {
            "name": "CLA check",
            "head_sha": last_commit.sha,
            "status": "completed",
            "conclusion": "action_required",
            "details_url": help_url,
            "output": {
                "title": "EasyCLA: Signed CLA not found",
                "summary": "One or more committers are authorized under a signed CLA.",
                "text": text,
            },
        }
        client.create_check_run(repository_name, json.dumps(payload))

    # Update the comment
    if both or notification == 'comment':
        body = cla.utils.assemble_cla_comment('github', str(installation_id), github_repository_id, pull_request.number,
                                              signed, missing)
        if not missing:
            # After Issue #167 wsa in place, they decided via Issue #289 that we
            # DO want to update the comment, but only after we've previously failed
            if has_check_previously_failed(pull_request):
                cla.log.debug('Found previously failed checks - updating CLA comment in PR.')
                update_cla_comment(pull_request, body)
            cla.log.debug('EasyCLA App checks pass for PR: {} with authors: {}'.format(pull_request.number, signed))
        else:
            # Per Issue #167, only add a comment if check fails
            update_cla_comment(pull_request, body)
            cla.log.debug('EasyCLA App checks fail for PR: {}. CLA signatures with signed authors: {} and '
                          'with missing authors: {}'.format(pull_request.number, signed, missing))

    if both or notification == 'status':
        context_name = os.environ.get('GH_STATUS_CTX_NAME')
        if context_name is None:
            context_name = 'communitybridge/cla'

        # if we have ANY committers who have failed the check - update the status with overall failure
        if missing is not None and len(missing) > 0:
            state = 'failure'
            # For status, we change the context from author_name to 'communitybridge/cla' or the
            # specified default value per issue #166
            context, body = cla.utils.assemble_cla_status(context_name, signed=False)
            sign_url = cla.utils.get_full_sign_url(
                'github', str(installation_id), github_repository_id, pull_request.number)
            cla.log.debug(f'Creating new CLA {state} status - {len(signed)} passed, {missing}, signing url: {sign_url}')
            create_commit_status(pull_request, last_commit.sha, state, sign_url, body, context)
        elif signed is not None and len(signed) > 0:
            state = 'success'
            # For status, we change the context from author_name to 'communitybridge/cla' or the
            # specified default value per issue #166
            context, body = cla.utils.assemble_cla_status(context_name, signed=True)
            sign_url = cla.conf["CLA_LANDING_PAGE"]  # Remove this once signature detail page ready.
            cla.log.debug(f'Creating new CLA {state} status - {len(signed)} passed, {missing}, signing url: {sign_url}')
            create_commit_status(pull_request, last_commit.sha, state, sign_url, body, context)
        else:
            # error condition - should have a least one committer and they would be in one of the above
            # lists: missing or signed
            state = 'failure'
            # For status, we change the context from author_name to 'communitybridge/cla' or the
            # specified default value per issue #166
            context, body = cla.utils.assemble_cla_status(context_name, signed=False)
            sign_url = cla.utils.get_full_sign_url(
                'github', str(installation_id), github_repository_id, pull_request.number)
            cla.log.debug(f'Creating new CLA {state} status - {len(signed)} passed, {missing}, signing url: {sign_url}')
            cla.log.warning('This is an error condition - should have at least one committer in one of these lists: '
                            f'{len(signed)} passed, {missing}')
            create_commit_status(pull_request, last_commit.sha, state, sign_url, body, context)


def create_commit_status(pull_request, commit_hash, state, sign_url, body, context):
    """
    Helper function to create a pull request commit status message given the PR and commit hash.

    :param pull_request: The GitHub Pull Request object.
    :type pull_request: github.PullRequest
    :param commit_hash: The commit hash to post a status on.
    :type commit_hash: string
    :param state: The state of the status.
    :type state: string
    :param sign_url: The link the user will be taken to when clicking on the status message.
    :type sign_url: string
    :param body: The contents of the status message.
    :type body: string
    """
    try:
        commit_obj = None
        for commit in pull_request.get_commits():
            if commit.sha == commit_hash:
                commit_obj = commit
                break
        if commit_obj is None:
            cla.log.error(f'Could not post status {state} on '
                          f'PR: {pull_request.number}, '
                          f'Commit: {commit_hash} not found')
            return
        # context is a string label to differentiate one signer status from another signer status.
        # committer name is used as context label
        commit_obj.create_status(state, sign_url, body, context)
        cla.log.info(f'Successfully posted status {state} on PR {pull_request.number}: Commit {commit_hash}')
    except GithubException as exc:
        cla.log.error(f'Could not post status {state} on PR: {pull_request.number}, '
                      f'Commit: {commit_hash}, '
                      f'Response Code: {exc.status}, '
                      f'Message: {exc.data}')


def update_cla_comment(pull_request, body):
    """
    Helper function to create/edit a comment on the GitHub PR.

    :param pull_request: The PR object in question.
    :type pull_request: GitHub.PullRequest
    :param body: The contents of the comment.
    :type body: string
    """
    comment = get_existing_cla_comment(pull_request)
    if comment is not None:
        cla.log.debug(f'Updating existing CLA comment for PR: {pull_request.number} with body: {body}')
        comment.edit(body)
    else:
        cla.log.debug(f'Creating a new CLA comment for PR: {pull_request.number} with body: {body}')
        pull_request.create_issue_comment(body)


def get_existing_cla_comment(pull_request):
    """
    Helper function to get an existing comment from the CLA system in a GitHub PR.

    :param pull_request: The PR object in question.
    :type pull_request: GitHub.PullRequest
    """
    comments = pull_request.get_issue_comments()
    for comment in comments:
        if '[![CLA Check](' in comment.body:
            cla.log.debug('Found matching CLA comment for PR: %s', pull_request.number)
            return comment


def get_github_integration_client(installation_id):
    """
    GitHub App integration client used for authenticated client actions through an installed app.
    """
    return GitHubInstallation(installation_id).api_object


def get_github_client(organization_id):
    github_org = cla.utils.get_github_organization_instance()
    github_org.load(organization_id)
    installation_id = github_org.get_organization_installation_id()
    return get_github_integration_client(installation_id)


class MockGitHub(GitHub):
    """
    The GitHub repository service mock class for testing.
    """

    def __init__(self, oauth2_token=False):
        super().__init__()
        self.oauth2_token = oauth2_token

    def _get_github_client(self, username, token):
        return MockGitHubClient(username, token)

    def _get_authorization_url_and_state(self, client_id, redirect_uri, scope, authorize_url):
        authorization_url = 'http://authorization.url'
        state = 'random-state-here'
        return authorization_url, state

    def _fetch_token(self, client_id, state, token_url, client_secret, code):  # pylint: disable=too-many-arguments
        return 'random-token'

    def _get_request_session(self, request):
        if self.oauth2_token:
            return {'github_oauth2_token': 'random-token',
                    'github_oauth2_state': 'random-state',
                    'github_origin_url': 'http://github/origin/url',
                    'github_installation_id': 1}
        return {}

    def get_user_data(self, session, client_id):
        return {'email': 'test@user.com', 'name': 'Test User', 'id': 123}

    def get_user_emails(self, session, client_id):
        return [{'email': 'test@user.com', 'verified': True, 'primary': True, 'visibility': 'public'}]

    def get_pull_request(self, github_repository_id, pull_request_number, installation_id):
        return MockGitHubPullRequest(pull_request_number)


class MockGitHubClient(object):  # pylint: disable=too-few-public-methods
    """
    The GitHub Client object mock class for testing.
    """

    def __init__(self, username, token):
        self.username = username
        self.token = token

    def get_repo(self, repository_id):  # pylint: disable=no-self-use
        """
        Mock version of the GitHub Client object's get_repo method.
        """
        return MockGitHubRepository(repository_id)


class MockGitHubRepository(object):  # pylint: disable=too-few-public-methods
    """
    The GitHub Repository object mock class for testing.
    """

    def __init__(self, repository_id):
        self.id = repository_id

    def get_pull(self, pull_request_id):  # pylint: disable=no-self-use
        """
        Mock version of the GitHub Repository object's get_pull method.
        """
        return MockGitHubPullRequest(pull_request_id)


class MockGitHubPullRequest(object):  # pylint: disable=too-few-public-methods
    """
    The GitHub PullRequest object mock class for testing.
    """

    def __init__(self, pull_request_id):
        self.number = pull_request_id
        self.html_url = 'http://test-github.com/user/repo/' + str(self.number)

    def get_commits(self):  # pylint: disable=no-self-use
        """
        Mock version of the GitHub PullRequest object's get_commits method.
        """
        lst = MockPaginatedList()
        lst._elements = [MockGitHubCommit()]  # pylint: disable=protected-access
        return lst

    def get_issue_comments(self):  # pylint: disable=no-self-use
        """
        Mock version of the GitHub PullRequest object's get_issue_comments method.
        """
        return [MockGitHubComment()]

    def create_issue_comment(self, body):  # pylint: disable=no-self-use
        """
        Mock version of the GitHub PullRequest object's create_issue_comment method.
        """
        pass


class MockGitHubComment(object):  # pylint: disable=too-few-public-methods
    """
    A GitHub mock issue comment object for testing.
    """
    body = 'Test'


class MockPaginatedList(github.PaginatedList.PaginatedListBase):  # pylint: disable=too-few-public-methods
    """Mock GitHub paginated list for testing purposes."""

    def __init__(self):
        super().__init__()
        # Need to use our own elements list (self.__elements from PaginatedListBase does not
        # work as expected).
        self._elements = []

    @property
    def reversed(self):
        """Fake reversed property."""
        return [MockGitHubCommit()]

    def __iter__(self):
        for element in self._elements:
            yield element


class MockGitHubCommit(object):  # pylint: disable=too-few-public-methods
    """
    The GitHub Commit object mock class for testing.
    """

    def __init__(self):
        self.author = MockGitHubAuthor()
        self.sha = 'sha-test-commit'

    def create_status(self, state, sign_url, body):
        """
        Mock version of the GitHub Commit object's create_status method.
        """
        pass


class MockGitHubAuthor(object):  # pylint: disable=too-few-public-methods
    """
    The GitHub Author object mock class for testing.
    """

    def __init__(self, author_id=1):
        self.id = author_id
        self.login = 'user'
        self.email = 'user@github.com'
