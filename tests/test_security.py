import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lambda' / 'ingest'))
from security import authorize


class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'COGNITO_ISSUER':'https://issuer.example/pool','COGNITO_CLIENT_ID':'test-client'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def event(self, groups=None, **changes):
        claims = {'iss':'https://issuer.example/pool','client_id':'test-client','token_use':'access','exp':time.time()+600,'sub':'test-user','scope':'aquacloud/read aquacloud/export','cognito:groups':groups if groups is not None else ['Viewer']}
        claims.update(changes)
        return {'requestContext':{'authorizer':{'claims':claims}}}

    def test_roles(self):
        for group in ['Viewer','Operator','Admin']:
            with self.subTest(group=group):
                self.assertIsNone(authorize(self.event([group]),'read'))
                self.assertEqual(authorize(self.event([group]),'export'),403 if group=='Viewer' else None)

    def test_missing_and_forged_claims(self):
        for event in [{}, {'body':'{"cognito:groups":["Admin"]}'}, {'headers':{'Authorization':'Bearer forged'}}]:
            self.assertEqual(authorize(event,'read'),401)

    def test_invalid_identity(self):
        for changes in [{'iss':'wrong'},{'client_id':'wrong'},{'token_use':'id'},{'exp':0},{'exp':'broken'},{'sub':''}]:
            self.assertEqual(authorize(self.event(**changes),'read'),401)

    def test_no_group_unknown_group_and_missing_scope(self):
        for groups in [[],['Administrators'],{'Admin':True},'[broken',42]:
            self.assertEqual(authorize(self.event(groups),'read'),403)
        self.assertEqual(authorize(self.event(['Admin'],scope='openid aquacloud/read'),'export'),403)

    def test_group_serialization(self):
        for groups in ['Viewer,Operator','["Admin"]',['Viewer','Admin']]:
            self.assertIsNone(authorize(self.event(groups),'export'))

    def test_missing_configuration_fails_closed(self):
        with patch.dict(os.environ, {'COGNITO_CLIENT_ID':''}):
            self.assertEqual(authorize(self.event(),'read'),503)

    def test_route_denial_has_no_storage_side_effects(self):
        with patch.dict(sys.modules, {'boto3':MagicMock(),'boto3.dynamodb':MagicMock(),'boto3.dynamodb.conditions':MagicMock()}):
            import lambda_function as handler
        for route, method in [('/dashboard','GET'),('/export','POST')]:
            with patch.object(handler,'handle_dashboard') as read, patch.object(handler,'handle_export') as export:
                result = handler.lambda_handler({'resource':route,'httpMethod':method},None)
                self.assertEqual(result['statusCode'],401)
                read.assert_not_called(); export.assert_not_called()
        with patch.object(handler,'handle_ingest',return_value={'statusCode':200}) as ingest:
            event = {'resource':'/readings','httpMethod':'POST','body':'{}'}
            self.assertEqual(handler.lambda_handler(event,None)['statusCode'],200)
            ingest.assert_called_once_with(event)


if __name__ == '__main__':
    unittest.main()
