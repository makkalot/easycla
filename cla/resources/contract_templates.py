"""
Holds various HTML contract templates.
"""

import os
import cla

class ContractTemplate(object):
    def __init__(self, document_type='Individual', major_version=1, minor_version=0, body=None):
        self.document_type = 'Individual'
        self.major_version = 1
        self.minor_version = 0
        self.body = body

    def get_html_contract(self, legal_entity_name, preamble):
        html = self.body
        if html is not None:
            html = html.replace('{{document_type}}', self.document_type)
            html = html.replace('{{major_version}}', str(self.major_version))
            html = html.replace('{{minor_version}}', str(self.minor_version))
            html = html.replace('{{legal_entity_name}}', legal_entity_name)
            html = html.replace('{{preamble}}', preamble)
        return html

    def get_tabs(self):
        return []

class TestTemplate(ContractTemplate):
    def __init__(self, document_type='Individual', major_version=1, minor_version=0, body=None):
        super().__init__(document_type, major_version, minor_version, body)
        if self.body is None:
            self.body = """
<html>
    <body>
        <h3 class="legal-entity-name" style="text-align: center">
            {{legal_entity_name}}<br />
            {{document_type}} Contributor License Agreement ("Agreement") v{{major_version}}.{{minor_version}}
        </h3>
        <div class="preamble">
            {{preamble}}
        </div>
        <p>If you have not already done so, please complete and sign, then scan and email a pdf file of this Agreement to cla@cncf.io.<br />If necessary, send an original signed Agreement to The Linux Foundation: 1 Letterman Drive, Building D, Suite D4700, San Francisco CA 94129, U.S.A.<br />Please read this document carefully before signing and keep a copy for your records.
        </p>
        <p>You accept and agree to the following terms and conditions for Your present and future Contributions submitted to the Foundation. In return, the Foundation shall not use Your Contributions in a way that is contrary to the public benefit or inconsistent with its nonprofit status and bylaws in effect at the time of the Contribution. Except for the license granted herein to the Foundation and recipients of software distributed by the Foundation, You reserve all right, title, and interest in and to Your Contributions
        </p>
    </body>
</html>"""

class CNCFTemplate(ContractTemplate):
    def __init__(self, document_type='Individual', major_version=1, minor_version=0):
        super().__init__(document_type, major_version, minor_version)
        cwd = os.path.dirname(os.path.realpath(__file__))
        fname = '%s/cncf-%s-cla.html' %(cwd, document_type.lower())
        self.body = open(fname).read()

    def get_tabs(self):
        return [
            {'type': 'text',
             'id': 'full_name',
             'name': 'Full Name',
             'position_x': 105,
             'position_y': 302,
             'width': 360,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'public_name',
             'name': 'Public Name',
             'position_x': 120,
             'position_y': 330,
             'width': 345,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'mailing_address_1',
             'name': 'Mailing Address1',
             'position_x': 140,
             'position_y': 358,
             'width': 325,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'mailing_address_2',
             'name': 'Mailing Address2',
             'position_x': 55,
             'position_y': 386,
             'width': 420,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'country',
             'name': 'Country',
             'position_x': 100,
             'position_y': 414,
             'width': 370,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'telephone',
             'name': 'Telephone',
             'position_x': 115,
             'position_y': 442,
             'width': 350,
             'height': 20,
             'page': 1},
            {'type': 'text',
             'id': 'email',
             'name': 'Email',
             'position_x': 90,
             'position_y': 470,
             'width': 380,
             'height': 20,
             'page': 1},
            {'type': 'sign',
             'id': 'sign',
             'name': 'Please Sign',
             'position_x': 180,
             'position_y': 140,
             'width': 0,
             'height': 0,
             'page': 3},
            {'type': 'date',
             'id': 'date',
             'name': 'Date',
             'position_x': 350,
             'position_y': 182,
             'width': 0,
             'height': 0,
             'page': 3}
        ]
