# Copyright 2016 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import jsonschema
import uuid

from oslo_serialization import jsonutils
import requests

from glare.api.v1 import resource
from glare.api.v1 import router
from glare.common import wsgi
from glare.tests import functional


def _create_resource():
    deserializer = resource.RequestDeserializer()
    serializer = resource.ResponseSerializer()
    controller = resource.ArtifactsController()
    return wsgi.Resource(controller, deserializer, serializer)


class TestRouter(router.API):
    def _get_artifacts_resource(self):
        return _create_resource()


def sort_results(lst, target='name'):
    return sorted(lst, key=lambda x: x[target])


class TestArtifact(functional.FunctionalTest):

    users = {
        'user1': {
            'id': str(uuid.uuid4()),
            'tenant_id': str(uuid.uuid4()),
            'token': str(uuid.uuid4()),
            'role': 'member'
        },
        'user2': {
            'id': str(uuid.uuid4()),
            'tenant_id': str(uuid.uuid4()),
            'token': str(uuid.uuid4()),
            'role': 'member'
        },
        'admin': {
            'id': str(uuid.uuid4()),
            'tenant_id': str(uuid.uuid4()),
            'token': str(uuid.uuid4()),
            'role': 'admin'
        },
        'anonymous': {
            'id': None,
            'tenant_id': None,
            'token': None,
            'role': None
        }
    }

    def setUp(self):
        super(TestArtifact, self).setUp()
        self.set_user('user1')
        self.glare_server.deployment_flavor = 'noauth'
        self.glare_server.enabled_artifact_types = 'sample_artifact'
        self.glare_server.custom_artifact_types_modules = (
            'glare.tests.functional.sample_artifact')
        self.start_servers(**self.__dict__.copy())

    def tearDown(self):
        self.stop_servers()
        self._reset_database(self.glare_server.sql_connection)
        super(TestArtifact, self).tearDown()

    def _url(self, path):
        if 'schemas' in path:
            return 'http://127.0.0.1:%d%s' % (self.glare_port, path)
        else:
            return 'http://127.0.0.1:%d/artifacts%s' % (self.glare_port, path)

    def set_user(self, username):
        if username not in self.users:
            raise KeyError
        self.current_user = username

    def _headers(self, custom_headers=None):
        base_headers = {
            'X-Identity-Status': 'Confirmed',
            'X-Auth-Token': self.users[self.current_user]['token'],
            'X-User-Id': self.users[self.current_user]['id'],
            'X-Tenant-Id': self.users[self.current_user]['tenant_id'],
            'X-Project-Id': self.users[self.current_user]['tenant_id'],
            'X-Roles': self.users[self.current_user]['role'],
        }
        base_headers.update(custom_headers or {})
        return base_headers

    def create_artifact(self, data=None, status=201):
        return self.post('/sample_artifact', data or {}, status=status)

    def _check_artifact_method(self, method, url, data=None, status=200,
                               headers=None):
        if not headers:
            headers = self._headers()
        else:
            headers = self._headers(headers)
        headers.setdefault("Content-Type", "application/json")
        if 'application/json' in headers['Content-Type'] and data is not None:
            data = jsonutils.dumps(data)
        response = getattr(requests, method)(self._url(url), headers=headers,
                                             data=data)
        self.assertEqual(status, response.status_code, response.text)
        if status >= 400:
            return response.text
        if ("application/json" in response.headers["content-type"] or
                "application/schema+json" in response.headers["content-type"]):
            return jsonutils.loads(response.text)
        return response.text

    def post(self, url, data=None, status=201, headers=None):
        return self._check_artifact_method("post", url, data, status=status,
                                           headers=headers)

    def get(self, url, status=200, headers=None):
        return self._check_artifact_method("get", url, status=status,
                                           headers=headers)

    def delete(self, url, status=204):
        response = requests.delete(self._url(url), headers=self._headers())
        self.assertEqual(status, response.status_code, response.text)
        return response.text

    def patch(self, url, data, status=200, headers=None):
        if headers is None:
            headers = {}
        if 'Content-Type' not in headers:
            headers.update({'Content-Type': 'application/json-patch+json'})
        return self._check_artifact_method("patch", url, data, status=status,
                                           headers=headers)

    def put(self, url, data=None, status=200, headers=None):
        return self._check_artifact_method("put", url, data, status=status,
                                           headers=headers)

    def test_artifact_lifecycle(self):
        # test that artifact is available artifact type
        response = self.get(url='/schemas', status=200)
        self.assertIn('sample_artifact', response['schemas'])

        # Getting empty artifact list
        url = '/sample_artifact'
        response = self.get(url=url, status=200)
        expected = {'first': '/artifacts/sample_artifact',
                    'sample_artifact': [],
                    'schema': '/schemas/sample_artifact'}
        self.assertEqual(expected, response)

        # Create an artifact (without any properties)
        af = self.create_artifact({'name': 'name5',
                                   'version': '1.0',
                                   'tags': ['tag4', 'tag5'],
                                   'int1': 2048,
                                   'float1': 987.654,
                                   'str1': 'lalala',
                                   'bool1': False})
        self.assertIsNotNone(af['id'])

        # Get the artifact which should have a generated id and status
        # 'queued'
        url = '/sample_artifact/%s' % af['id']
        af = self.get(url=url, status=200)
        self.assertEqual('queued', af['status'])
        self.assertEqual('private', af['visibility'])

        # Artifact list should now have one entry
        url = '/sample_artifact'
        response = self.get(url=url, status=200)
        self.assertEqual(1, len(response['sample_artifact']))

        # Change artifact properties with patch request
        url = '/sample_artifact/%s' % af['id']
        patch = [{'op': 'replace',
                  'value': 'I am the string',
                  'path': '/string_mutable'}]
        af = self.patch(url=url, data=patch, status=200)
        self.assertEqual('I am the string', af['string_mutable'])
        patch = [{'op': 'replace',
                  'value': 'test',
                  'path': '/description'},
                 {'op': 'replace',
                  'value': 'I am another string',
                  'path': '/str1'}]
        af = self.patch(url=url, data=patch, status=200)
        self.assertEqual('I am another string', af['str1'])
        self.assertEqual('test', af['description'])

        # Check that owner cannot be modified
        system_update_patch = [
            {'op': 'replace',
             'value': 'any_value',
             'path': '/owner'}
        ]
        self.patch(url=url, data=system_update_patch, status=403)

        # Add new values to artifact metadata
        patch = [{'op': 'add',
                  'value': 'custom_value1',
                  'path': '/metadata/custom_prop1'},
                 {'op': 'add',
                  'value': 'custom_value2',
                  'path': '/metadata/custom_prop2'}
                 ]
        af = self.patch(url=url, data=patch, status=200)
        self.assertEqual('custom_value1', af['metadata']['custom_prop1'])
        self.assertEqual('custom_value2', af['metadata']['custom_prop2'])

        # Remove prop from artifact metadata
        patch = [{'op': 'remove',
                  'path': '/metadata/custom_prop1'}]
        af = self.patch(url=url, data=patch, status=200)
        self.assertNotIn('custom_prop', af['metadata'])
        self.assertEqual('custom_value2', af['metadata']['custom_prop2'])

        # Adding new property 'foo' to the artifact returns 400 error
        patch = [{'op': 'add',
                  'value': 'bar',
                  'path': '/foo'}]
        self.patch(url=url, data=patch, status=400)

        # Removing property 'name' from the artifact returns 400 error
        patch = [{'op': 'remove',
                  'value': 'name',
                  'path': '/name'}]
        self.patch(url=url, data=patch, status=400)

        # Activation of the artifact should fail with 400 error
        url = '/sample_artifact/%s' % af['id']
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        self.patch(url=url, data=data, status=400)

        # Uploading file to the property 'name' of the artifact should fail
        # with 400 error
        headers = {'Content-Type': 'application/octet-stream'}
        data = "data" * 100
        self.put(url=url + '/name', data=data, status=400, headers=headers)

        # Downloading 'blob' from the artifact should fail with 400 error
        self.get(url=url + '/blob', status=400)

        # Upload file to the artifact
        af = self.put(url=url + '/blob', data=data, status=200,
                      headers=headers)
        self.assertEqual('active', af['blob']['status'])

        # Modifying status for blob leads to 400 error
        patch = [{'op': 'replace',
                  'value': 'saving',
                  'path': '/blob/status'}]
        self.patch(url=url, data=patch, status=400)

        # Set required string
        patch = [{'op': 'replace',
                  'value': 'I am required string',
                  'path': '/string_required'}]
        af = self.patch(url=url, data=patch, status=200)
        self.assertEqual('I am required string', af['string_required'])

        # Get the artifact, blob property should have status 'active'
        af = self.get(url=url, status=200)
        self.assertEqual('active', af['blob']['status'])

        # Activate the artifact and check that it has status 'active'
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        af = self.patch(url=url, data=data, status=200)
        self.assertEqual('active', af['status'])

        # Changing immutable container format of the artifact fails with
        # 400 error
        patch = [{'op': 'replace',
                  'value': 'I am new string',
                  'path': '/string_required'}]
        self.patch(url=url, data=patch, status=403)

        # Adding a description of the artifact after activation is okay
        patch = [{'op': 'add',
                  'value': 'I am the artifact!',
                  'path': '/description'}]
        self.patch(url=url, data=patch, status=200)

        # Deactivate the artifact with admin and check that it has status
        # 'deactivated'
        self.set_user('admin')
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "deactivated"
        }]
        af = self.patch(url=url, data=data, status=200)
        self.assertEqual('deactivated', af['status'])

        # Only admin can download de-activated artifacts
        self.assertEqual("data" * 100,
                         self.get(url=url + '/blob', status=200))

        # Reactivate the artifact and check that it has status 'active'
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        af = self.patch(url=url, data=data, status=200)
        self.assertEqual('active', af['status'])

        # Delete the artifact
        self.set_user('user1')
        self.delete(url=url, status=204)
        self.get(url=url, status=404)

    def test_blob_dicts(self):
        # Getting empty artifact list
        url = '/sample_artifact'
        response = self.get(url=url, status=200)
        expected = {'first': '/artifacts/sample_artifact',
                    'sample_artifact': [],
                    'schema': '/schemas/sample_artifact'}
        self.assertEqual(expected, response)

        # Create a test artifact
        art = self.create_artifact(status=201, data={'name': 'test',
                                                     'version': '1.0',
                                                     'string_required': '123'})
        self.assertIsNotNone(art['id'])

        # Get the artifact which should have a generated id and status 'queued'
        url = '/sample_artifact/%s' % art['id']
        art_1 = self.get(url=url, status=200)
        self.assertIsNotNone(art_1['id'])
        self.assertEqual('queued', art_1['status'])

        # Upload data to blob dict
        headers = {'Content-Type': 'application/octet-stream'}
        data = "data" * 100

        self.put(url=url + '/dict_of_blobs/new_blob',
                 data=data, status=200, headers=headers)

        # Download data from blob dict
        self.assertEqual(data, self.get(url=url + '/dict_of_blobs/new_blob',
                                        status=200))

        # download blob from undefined dict property
        self.get(url=url + '/not_a_dict/not_a_blob', status=400)

    def test_artifact_marker_and_limit(self):
        # Create artifacts
        art_list = [self.create_artifact({'name': 'name%s' % i,
                                          'version': '1.0',
                                          'tags': ['tag%s' % i],
                                          'int1': 1024 + i,
                                          'float1': 123.456,
                                          'str1': 'bugaga',
                                          'bool1': True})
                    for i in range(5)]
        # Sorting by several custom columns leads to 400 error
        url = '/sample_artifact?limit=1&sort=float1:asc,int1:asc,name:desc'
        self.get(url=url, status=400)

        # sort by 'next' url
        url = '/sample_artifact?limit=1&sort=int1:asc,name:desc'
        result = self.get(url=url)
        self.assertEqual([art_list[0]], result['sample_artifact'])
        marker = result['next']
        result = self.get(url=marker[10:])
        self.assertEqual([art_list[1]], result['sample_artifact'])

        # sort by custom marker
        url = '/sample_artifact?sort=int1:asc&marker=%s' % art_list[1]['id']
        result = self.get(url=url)
        self.assertEqual(art_list[2:], result['sample_artifact'])
        url = '/sample_artifact?sort=int1:desc&marker=%s' % art_list[1]['id']
        result = self.get(url=url)
        self.assertEqual(art_list[:1], result['sample_artifact'])
        url = '/sample_artifact' \
              '?sort=float1:asc,name:desc&marker=%s' % art_list[1]['id']
        result = self.get(url=url)
        self.assertEqual([art_list[0]], result['sample_artifact'])

        # paginate by name in desc order with limit 2
        url = '/sample_artifact?limit=2&sort=name:desc'
        result = self.get(url=url)
        self.assertEqual(art_list[4:2:-1], result['sample_artifact'])
        marker = result['next']
        result = self.get(url=marker[10:])
        self.assertEqual(art_list[2:0:-1], result['sample_artifact'])
        marker = result['next']
        result = self.get(url=marker[10:])
        self.assertEqual([art_list[0]], result['sample_artifact'])

    def test_artifact_filters(self):
        # Create artifact
        art_list = [self.create_artifact({'name': 'name%s' % i,
                                          'version': '1.0',
                                          'tags': ['tag%s' % i],
                                          'int1': 1024,
                                          'float1': 123.456,
                                          'str1': 'bugaga',
                                          'bool1': True})
                    for i in range(5)]

        public_art = self.create_artifact({'name': 'name5',
                                           'version': '1.0',
                                           'tags': ['tag4', 'tag5'],
                                           'int1': 2048,
                                           'float1': 987.654,
                                           'str1': 'lalala',
                                           'bool1': False,
                                           'string_required': '123'})
        url = '/sample_artifact/%s' % public_art['id']
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        self.patch(url=url, data=data, status=200)
        public_art = self.publish_with_admin(public_art['id'])
        art_list.append(public_art)

        art_list.sort(key=lambda x: x['name'])

        url = '/sample_artifact?str1=bla:empty'
        self.get(url=url, status=400)

        url = '/sample_artifact?str1=bla:empty'
        self.get(url=url, status=400)

        url = '/sample_artifact?name=name0'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([art_list[0]], result)

        url = '/sample_artifact?tags=tag4'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[4:], result)

        url = '/sample_artifact?name=eq:name0'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:1], result)

        url = '/sample_artifact?str1=eq:bugaga'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?int1=eq:2048'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        url = '/sample_artifact?float1=eq:123.456'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?name=neq:name0'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[1:], result)

        url = '/sample_artifact?name=in:name,name0'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:1], result)

        url = '/sample_artifact?name=in:not_exist,name0'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:1], result)

        url = '/sample_artifact?name=not_exist'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?name=bla:name1'
        self.get(url=url, status=400)

        url = '/sample_artifact?name='
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?name=eq:'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?tags=tag4,tag5'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        url = '/sample_artifact?tags-any=tag4'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[4:], result)

        url = '/sample_artifact?tags=tag4,tag_not_exist,tag5'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?tags-any=tag4,tag_not_exist,tag5'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[4:], result)

        url = '/sample_artifact?tags=tag_not_exist,tag_not_exist_1'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?tags'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list, result)

        url = '/sample_artifact?tags='
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list, result)

        url = '/sample_artifact?tags=eq:tag0'
        self.get(url=url, status=400)

        url = '/sample_artifact?tags=bla:tag0'
        self.get(url=url, status=400)

        url = '/sample_artifact?tags=neq:tag1'
        self.get(url=url, status=400)

        url = '/sample_artifact?visibility=private'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?visibility=public'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        url = '/sample_artifact?visibility=eq:private'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?visibility=eq:public'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        # visibility=neq:private
        url = '/sample_artifact?visibility=neq:private'
        self.get(url=url, status=400)

        url = '/sample_artifact?visibility=neq:public'
        self.get(url=url, status=400)

        url = '/sample_artifact?visibility=blabla'
        self.get(url=url, status=200)

        url = '/sample_artifact?visibility=neq:blabla'
        self.get(url=url, status=400)

        url = '/sample_artifact?name=eq:name0&name=name1&tags=tag1'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual([], result)

        url = '/sample_artifact?int1=gt:2000'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        url = '/sample_artifact?int1=lte:1024'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?int1=gt:1000&int1=lt:2000'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?int1=lt:2000'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?float1=gt:200.000'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

        url = '/sample_artifact?float1=gt:100.00&float1=lt:200.00'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?float1=lt:200.00'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?float1=lt:200'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?float1=lte:123.456'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?bool1=True'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:5], result)

        url = '/sample_artifact?bool1=False'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[5:], result)

    def test_artifact_dict_prop_filters(self):
        # Create artifact
        art_list = [self.create_artifact({'name': 'name0',
                                          'version': '1.0',
                                          'dict_of_str': {'pr1': 'val1'}}),
                    self.create_artifact({'name': 'name1',
                                          'version': '1.0',
                                          'dict_of_str': {'pr1': 'val1',
                                                          'pr2': 'val2'}}),
                    self.create_artifact({'name': 'name2',
                                          'version': '1.0',
                                          'dict_of_str': {'pr3': 'val3'}}),
                    self.create_artifact({'name': 'name3',
                                          'version': '1.0',
                                          'dict_of_str': {'pr3': 'val1'},
                                          'dict_of_int': {"1": 10, "2": 20}}),
                    self.create_artifact({'name': 'name4',
                                          'version': '1.0',
                                          'dict_of_str': {},
                                          'dict_of_int': {"2": 20, "3": 30}}),
                    ]

        art_list.sort(key=lambda x: x['name'])

        url = '/sample_artifact?dict_of_str.pr1=val1'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:2], result)

        url = '/sample_artifact?dict_of_int.1=10'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[3:4], result)

        url = '/sample_artifact?dict_of_str.pr1=val999'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([], result)

        url = '/sample_artifact?dict_of_str.pr1=eq:val1'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual(art_list[:2], result)

        url = '/sample_artifact?dict_of_str.'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([], result)

        for op in ['in', 'gt', 'gte', 'lt', 'lte', 'neq']:
            url = '/sample_artifact?dict_of_str.pr3=%s:val3' % op
            self.get(url=url, status=400)

        url = '/sample_artifact?dict_of_str.pr3=blabla:val3'
        self.get(url=url, status=400)

        url = '/sample_artifact?dict_of_str.pr1='
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([], result)

        url = '/sample_artifact?dict_of_str.pr1='
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([], result)

        url = '/sample_artifact?dict_of_str'
        self.get(url=url, status=400)

        url = '/sample_artifact?dict_of_str.pr3=blabla:val3'
        self.get(url=url, status=400)

        url = '/sample_artifact?dict_of_str.bla=val1'
        result = sort_results(self.get(url=url)['sample_artifact'])
        self.assertEqual([], result)

        url = '/sample_artifact?dict_of_int.1=lala'
        self.get(url=url, status=400)

    def test_artifact_tags(self):
        # Create artifact
        art = self.create_artifact({'name': 'name5',
                                    'version': '1.0',
                                    'tags': ['tag1', 'tag2', 'tag3'],
                                    'int1': 2048,
                                    'float1': 987.654,
                                    'str1': 'lalala',
                                    'bool1': False,
                                    'string_required': '123'})
        self.assertIsNotNone(art['id'])

        url = '/sample_artifact/%s' % art['id']
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        art = self.patch(url=url, data=data, status=200)
        self.assertEqual('active', art['status'])
        art = self.publish_with_admin(art['id'])
        self.assertEqual('public', art['visibility'])
        # only admins can update tags for public artifacts
        self.set_user("admin")
        # Check that tags created correctly
        url = '/sample_artifact/%s/tags' % art['id']
        tags = self.get(url=url, status=200)
        for tag in ['tag1', 'tag2', 'tag3']:
            self.assertIn(tag, tags['tags'])

        # Get the list of tags
        url = '/sample_artifact/%s/tags' % art['id']
        tags = self.get(url=url, status=200)
        for tag in ['tag1', 'tag2', 'tag3']:
            self.assertIn(tag, tags['tags'])

        # Set new tag list to the art
        body = {"tags": ["new_tag1", "new_tag2", "new_tag3"]}
        tags = self.put(url=url, data=body, status=200)
        for tag in ['new_tag1', 'new_tag2', 'new_tag3']:
            self.assertIn(tag, tags['tags'])

        # Delete all tags from the art
        url = '/sample_artifact/%s/tags' % art['id']
        self.delete(url=url, status=204)

        # Get the list of tags
        url = '/sample_artifact/%s/tags' % art['id']
        tags = self.get(url=url, status=200)
        self.assertEqual([], tags['tags'])

        # Modifing tags with PATCH leads to 400 error
        url = '/sample_artifact/%s' % art['id']
        patch = [{'op': 'remove',
                  'path': '/tags'}]
        self.patch(url=url, data=patch, status=400)

    def test_add_custom_location(self):
        # Create artifact
        art = self.create_artifact({'name': 'name5',
                                    'version': '1.0',
                                    'tags': ['tag1', 'tag2', 'tag3'],
                                    'int1': 2048,
                                    'float1': 987.654,
                                    'str1': 'lalala',
                                    'bool1': False,
                                    'string_required': '123'})
        self.assertIsNotNone(art['id'])

        # Set custom location
        url = '/sample_artifact/%s' % art['id']
        body = jsonutils.dumps(
            {'url': 'https://www.apache.org/licenses/LICENSE-2.0.txt'})
        headers = {'Content-Type':
                   'application/vnd+openstack.glare-custom-location+json'}
        self.put(url=url + '/blob', data=body,
                 status=200, headers=headers)

        # test re-add failed
        self.put(url=url + '/blob', data=body, status=409, headers=headers)
        # add to non-existing property
        self.put(url=url + '/blob_non_exist', data=body, status=400,
                 headers=headers)

        # Get the artifact, blob property should have status 'active'
        art = self.get(url=url, status=200)
        self.assertEqual('active', art['blob']['status'])
        self.assertIsNotNone(art['blob']['checksum'])
        self.assertEqual(3967, art['blob']['size'])
        self.assertEqual('text/plain', art['blob']['content_type'])
        self.assertNotIn('url', art['blob'])
        self.assertNotIn('id', art['blob'])

        # Set custom location
        url = '/sample_artifact/%s' % art['id']
        self.put(url=url + '/dict_of_blobs/blob', data=body,
                 status=200, headers=headers)

        # Get the artifact, blob property should have status 'active'
        art = self.get(url=url, status=200)
        self.assertEqual('active', art['dict_of_blobs']['blob']['status'])
        self.assertIsNotNone(art['dict_of_blobs']['blob']['checksum'])
        self.assertEqual(3967, art['dict_of_blobs']['blob']['size'])
        self.assertEqual('text/plain',
                         art['dict_of_blobs']['blob']['content_type'])
        self.assertNotIn('url', art['dict_of_blobs']['blob'])
        self.assertNotIn('id', art['dict_of_blobs']['blob'])
        # test re-add failed
        self.put(url=url + '/dict_of_blobs/blob', data=body, status=409,
                 headers=headers)

        # test request failed with non-json containment
        self.put(url=url + '/dict_of_blobs/blob_incorrect', data="incorrect",
                 status=400, headers=headers)

    def test_artifact_version(self):
        # Create artifacts with versions
        version_list = ['1.0', '1.1', '2.0.0', '2.0.1-beta', '2.0.1', '20.0']

        # Create artifact
        art_list = [self.create_artifact({'name': 'name',
                                          'version': version_list[i - 1],
                                          'tags': ['tag%s' % i],
                                          'int1': 2048,
                                          'float1': 123.456,
                                          'str1': 'bugaga',
                                          'bool1': True})
                    for i in range(1, 7)]

        public_art = self.create_artifact(
            {'name': 'name',
             'tags': ['tag4', 'tag5'],
             'int1': 1024,
             'float1': 987.654,
             'str1': 'lalala',
             'bool1': False,
             'string_required': '123'})
        url = '/sample_artifact/%s' % public_art['id']
        data = [{
            "op": "replace",
            "path": "/status",
            "value": "active"
        }]
        self.patch(url=url, data=data, status=200)
        public_art = self.publish_with_admin(public_art['id'])
        art_list.insert(0, public_art)

        expected_result = sort_results(art_list, target='version')
        url = '/sample_artifact'
        result = sort_results(self.get(url=url)['sample_artifact'],
                              target='version')
        self.assertEqual(expected_result, result)

        # Creating an artifact with existing version fails
        self.create_artifact(
            {'name': 'name',
             'version': '1.0',
             'tags': ['tag1'],
             'int1': 2048,
             'float1': 123.456,
             'str1': 'bugaga',
             'bool1': True},
            status=409)

        url = '/sample_artifact?name=name&version=gte:2.0.0'
        result = sort_results(self.get(url=url)['sample_artifact'],
                              target='version')
        self.assertEqual(expected_result[3:], result)

        url = ('/sample_artifact?'
               'name=name&version=gte:1.1&version=lt:2.0.1-beta')
        result = sort_results(self.get(url=url)['sample_artifact'],
                              target='version')
        self.assertEqual(expected_result[2:4], result)

        # Filtering by version without name is ok
        url = '/sample_artifact?version=gte:2.0.0'
        self.get(url=url, status=200)

        # Several name filters with version is ok
        url = '/sample_artifact?name=name&name=anothername&version=gte:2.0.0'
        self.get(url=url, status=200)

        # Filtering by version with name filter op different from 'eq'
        url = '/sample_artifact?version=gte:2.0.0&name=neq:name'
        self.get(url=url, status=200)

        # Sorting by version 'asc'
        url = '/sample_artifact?name=name&sort=version:asc'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual(art_list, result)

        # Sorting by version 'desc'
        url = '/sample_artifact?name=name&sort=version:desc'
        result = self.get(url=url)['sample_artifact']
        self.assertEqual(list(reversed(art_list)), result)

    # the test cases below are written in accordance with use cases
    # each test tries to cover separate use case in Glare
    # all code inside each test tries to cover all operators and data
    # involved in use case execution
    # each tests represents part of artifact lifecycle
    # so we can easily define where is the failed code

    make_active = [{"op": "replace", "path": "/status", "value": "active"}]

    def activate_with_admin(self, artifact_id, status=200):
        cur_user = self.current_user
        self.set_user('admin')
        url = '/sample_artifact/%s' % artifact_id
        af = self.patch(url=url, data=self.make_active, status=status)
        self.set_user(cur_user)
        return af

    make_deactivated = [{"op": "replace", "path": "/status",
                         "value": "deactivated"}]

    def deactivate_with_admin(self, artifact_id, status=200):
        cur_user = self.current_user
        self.set_user('admin')
        url = '/sample_artifact/%s' % artifact_id
        af = self.patch(url=url, data=self.make_deactivated, status=status)
        self.set_user(cur_user)
        return af

    make_public = [{"op": "replace", "path": "/visibility", "value": "public"}]

    def publish_with_admin(self, artifact_id, status=200):
        cur_user = self.current_user
        self.set_user('admin')
        url = '/sample_artifact/%s' % artifact_id
        af = self.patch(url=url, data=self.make_public, status=status)
        self.set_user(cur_user)
        return af

    def test_create_artifact(self):
        """All tests related to artifact creation"""
        # check that cannot create artifact for non-existent artifact type
        self.post('/incorrect_artifact', {}, status=404)
        # check that cannot accept non-json body
        self.post('/incorrect_artifact', "incorrect_body", status=400)
        # check that cannot accept incorrect content type
        self.post('/sample_artifact', {}, status=415,
                  headers={"Content-Type": "application/octet-stream"})
        # check that cannot create artifact without name
        self.create_artifact(data={"int1": 1024}, status=400)
        # check that cannot create artifact with too long name
        self.create_artifact(data={"name": "t" * 256}, status=400)
        # check that cannot create artifact with empty name
        self.create_artifact(data={"name": ""}, status=400)
        # check that can create af without version
        private_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str"})
        # check that default is set on artifact create
        uuid.UUID(private_art['id'])
        self.assertEqual('0.0.0', private_art['version'])
        self.assertEqual("default", private_art["system_attribute"])
        self.assertEqual(self.users['user1']['tenant_id'],
                         private_art['owner'])

        # check that cannot create artifact with invalid version
        self.create_artifact(data={"name": "test_af",
                                   "version": "dummy_version"}, status=400)
        # check that cannot create artifact with empty and long version
        self.create_artifact(data={"name": "test_af",
                                   "version": ""}, status=400)
        # check that cannot create artifact with empty and long version
        self.create_artifact(data={"name": "test_af",
                                   "version": "t" * 256}, status=400)
        # check that artifact artifact with the same name-version cannot
        # be created
        self.create_artifact(data={"name": "test_af"}, status=409)
        # check that we cannot create af with the same version but different
        # presentation
        self.create_artifact(data={"name": "test_af", "version": "0.0"},
                             status=409)
        # check that we can create artifact with different version and tags
        new_af = self.create_artifact(
            data={"name": "test_af", "version": "0.0.1",
                  "tags": ["tag1", "tag2"]})
        self.assertEqual(["tag1", "tag2"], new_af["tags"])
        # check that we cannot create artifact with visibility
        self.create_artifact(data={"name": "test_af", "version": "0.0.2",
                                   "visibility": "private"}, status=400)
        # check that we cannot create artifact with system property
        self.create_artifact(data={"name": "test_af", "version": "0.0.2",
                                   "system_attribute": "test"}, status=403)
        # check that we cannot specify blob in create
        self.create_artifact(data={"name": "test_af", "version": "0.0.2",
                                   "blob": {
                                       'url': None, 'size': None,
                                       'checksum': None, 'status': 'saving',
                                       'external': False}}, status=400)
        # check that anonymous user cannot create artifact
        self.set_user("anonymous")
        self.create_artifact(data={"name": "test_af", "version": "0.0.2"},
                             status=403)
        # check that another user can create artifact
        # with the same name version
        self.set_user("user2")
        some_af = self.create_artifact(data={"name": "test_af"})

        # check we can create artifact with all available attributes
        # (except blobs and system)
        expected = {
            "name": "test_big_create",
            "dependency1": "/artifacts/sample_artifact/%s" % some_af['id'],
            "bool1": True,
            "int1": 2323,
            "float1": 0.1,
            "str1": "test",
            "list_of_str": ["test"],
            "list_of_int": [0],
            "dict_of_str": {"test": "test"},
            "dict_of_int": {"test": 0},
            "string_mutable": "test",
            "string_required": "test",
        }
        big_af = self.create_artifact(data=expected)
        actual = {}
        for k in expected:
            actual[k] = big_af[k]
        self.assertEqual(expected, actual)
        # check that we cannot access artifact from other user
        # check that active artifact is not available for other user
        url = '/sample_artifact/%s' % private_art['id']
        self.get(url, status=404)
        # check we cannot create af with non-existing property
        self.create_artifact(data={"name": "test_af_ne",
                                   "non_exist": "non_exist"}, status=400)
        # activate and publish artifact to check that we can create
        # private artifact with the same name version
        self.set_user("user1")

        self.patch(url=url, data=self.make_active)
        self.publish_with_admin(private_art['id'])
        self.create_artifact(data={"name": "test_af",
                                   "string_required": "test_str"})

    def test_manage_dependencies(self):
        some_af = self.create_artifact(data={"name": "test_af"})
        dep_af = self.create_artifact(data={"name": "test_dep_af"})
        dep_url = "/artifacts/sample_artifact/%s" % some_af['id']

        # set valid dependency
        patch = [{"op": "replace", "path": "/dependency1", "value": dep_url}]
        url = '/sample_artifact/%s' % dep_af['id']
        af = self.patch(url=url, data=patch)
        self.assertEqual(af['dependency1'], dep_url)

        # remove dependency from artifact
        patch = [{"op": "replace", "path": "/dependency1", "value": None}]
        af = self.patch(url=url, data=patch)
        self.assertIsNone(af['dependency1'])

        # try to set invalid dependency
        patch = [{"op": "replace", "path": "/dependency1", "value": "Invalid"}]
        self.patch(url=url, data=patch, status=400)

    def test_update_artifact_before_activate(self):
        """Test updates for artifact before activation"""
        # create artifact to update
        private_art = self.create_artifact(data={"name": "test_af"})
        url = '/sample_artifact/%s' % private_art['id']
        # check we can update artifact
        change_version = [{
            "op": "replace",
            "path": "/version",
            "value": "0.0.2"
        }]
        self.patch(url=url, data=change_version)

        # wrong patch format fails with 400 error
        invalid_patch = {
            "op": "replace",
            "path": "/version",
            "value": "0.0.2"
        }
        self.patch(url=url, data=invalid_patch, status=400)

        # check that we cannot update af if af with
        # the same name or version exists
        dup_version = self.create_artifact(
            data={"name": "test_af", "version": "0.0.1"})
        dupv_url = '/sample_artifact/%s' % dup_version['id']
        change_version_dup = [{
            "op": "replace",
            "path": "/version",
            "value": "0.0.2"
        }]
        self.patch(url=dupv_url, data=change_version_dup, status=409)

        dup_name = self.create_artifact(data={"name": "test_name_af",
                                              "version": "0.0.2"})
        dupn_url = '/sample_artifact/%s' % dup_name['id']
        change_name = [{
            "op": "replace",
            "path": "/name",
            "value": "test_af"
        }]
        self.patch(url=dupn_url, data=change_name, status=409)
        # check that we can update artifacts dup
        # after first artifact updated name and version
        change_version[0]['value'] = "0.0.3"
        self.patch(url=url, data=change_version)
        self.patch(url=dupn_url, data=change_name)
        # check that we can update artifact dupv to target version
        # also check that after deletion of artifact with the same name
        # version I can update dupv
        self.delete(dupn_url)
        self.patch(url=dupv_url, data=change_version_dup)
        # check we cannot update artifact with incorrect content-type
        self.patch(url, {}, status=415,
                   headers={"Content-Type": "application/json"})
        # check we cannot update tags with patch
        set_tags = [{
            "op": "replace",
            "path": "/tags",
            "value": "test_af"
        }]
        self.patch(url, set_tags, status=400)
        # check we cannot update artifact with incorrect json-patch
        self.patch(url, "incorrect json patch", status=400)
        # check update is correct if there is no update
        no_name_update = [{
            "op": "replace",
            "path": "/name",
            "value": "test_af"
        }]
        self.patch(url, no_name_update)
        # check add new property request rejected
        add_prop = [{
            "op": "add",
            "path": "/string1",
            "value": "test_af"
        }]
        self.patch(url, add_prop, 400)
        # check delete property request rejected
        add_prop[0]["op"] = "remove"
        add_prop[0]["path"] = "/string_required"
        self.patch(url, add_prop, 400)
        # check we cannot update system attr with patch
        system_attr = [{
            "op": "replace",
            "path": "/system_attribute",
            "value": "dummy"
        }]
        self.patch(url, system_attr, 403)
        # check cannot update blob attr with patch
        blob_attr = [{
            "op": "replace",
            "path": "/blob",
            "value": {"name": "test_af", "version": "0.0.2",
                      "blob": {'url': None, 'size': None, 'checksum': None,
                               'status': 'saving', 'external': False}}}]
        self.patch(url, blob_attr, 400)
        blob_attr[0]["path"] = "/dict_of_blobs/-"
        blob_attr[0]["op"] = "add"
        self.patch(url, blob_attr, 400)
        # test update correctness for all attributes
        big_update_patch = [
            {"op": "replace", "path": "/bool1", "value": True},
            {"op": "replace", "path": "/int1", "value": 2323},
            {"op": "replace", "path": "/float1", "value": 0.1},
            {"op": "replace", "path": "/str1", "value": "test"},
            {"op": "replace", "path": "/list_of_str", "value": ["test"]},
            {"op": "replace", "path": "/list_of_int", "value": [0]},
            {"op": "replace", "path": "/dict_of_str",
             "value": {"test": "test"}},
            {"op": "replace", "path": "/dict_of_int",
             "value": {"test": 0}},
            {"op": "replace", "path": "/string_mutable", "value": "test"},
            {"op": "replace", "path": "/string_required", "value": "test"},
        ]
        upd_af = self.patch(url, big_update_patch)
        for patch_item in big_update_patch:
            self.assertEqual(patch_item.get("value"),
                             upd_af[patch_item.get("path")[1:]])

        # check we can update private artifact
        # to the same name version as public artifact
        self.patch(url=url, data=self.make_active)
        self.publish_with_admin(private_art['id'])
        self.patch(url=dupv_url, data=change_version)

    def test_artifact_activate(self):
        # create artifact to update
        private_art = self.create_artifact(
            data={"name": "test_af",
                  "version": "0.0.1"})
        # cannot activate artifact without required for activate attributes
        url = '/sample_artifact/%s' % private_art['id']
        self.patch(url=url, data=self.make_active, status=400)
        add_required = [{
            "op": "replace",
            "path": "/string_required",
            "value": "string"
        }]
        self.patch(url=url, data=add_required)
        # cannot activate if body contains non status changes
        incorrect = self.make_active + [{"op": "replace",
                                         "path": "/name",
                                         "value": "test"}]
        self.patch(url=url, data=incorrect, status=400)
        # can activate if body contains only status changes
        make_active_without_updates = self.make_active + add_required
        active_art = self.patch(url=url, data=make_active_without_updates)
        private_art['status'] = 'active'
        private_art['activated_at'] = active_art['activated_at']
        private_art['updated_at'] = active_art['updated_at']
        private_art['string_required'] = 'string'
        self.assertEqual(private_art, active_art)
        # check that active artifact is not available for other user
        self.set_user("user2")
        self.get(url, status=404)
        self.set_user("user1")

        # test that activate is idempotent
        self.patch(url=url, data=self.make_active)
        # test activate deleted artifact
        self.delete(url=url)
        self.patch(url=url, data=self.make_active, status=404)

    def test_artifact_publish(self):
        # create artifact to update
        self.set_user('admin')
        private_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})

        url = '/sample_artifact/%s' % private_art['id']
        self.patch(url=url, data=self.make_active)

        # test that only visibility must be specified in the request
        incorrect = self.make_public + [{"op": "replace",
                                         "path": "/string_mutable",
                                         "value": "test"}]
        self.patch(url=url, data=incorrect, status=400)
        # check public artifact
        public_art = self.patch(url=url, data=self.make_public)
        private_art['activated_at'] = public_art['activated_at']
        private_art['visibility'] = 'public'
        private_art['status'] = 'active'
        private_art['updated_at'] = public_art['updated_at']
        self.assertEqual(private_art, public_art)
        # check that public artifact available for simple user
        self.set_user("user1")
        self.get(url)
        self.set_user("admin")
        # test that artifact publish with the same name and version failed
        duplicate_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        dup_url = '/sample_artifact/%s' % duplicate_art['id']
        # test that we cannot publish queued artifact
        self.patch(url=dup_url, data=self.make_public, status=400)
        # proceed with duplicate testing
        self.patch(url=dup_url, data=self.make_active)
        self.patch(url=dup_url, data=self.make_public, status=409)
        # test that cannot publish deactivated artifact
        self.patch(dup_url, data=self.make_deactivated)
        self.patch(dup_url, data=self.make_public, status=400)

    def test_artifact_update_after_activate_and_publish(self):
        # activate artifact
        private_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})

        url = '/sample_artifact/%s' % private_art['id']
        self.patch(url=url, data=self.make_active)
        # test that immutable properties cannot be updated
        upd_immutable = [{
            "op": "replace",
            "path": "/name",
            "value": "new_name"
        }]
        self.patch(url, upd_immutable, status=403)
        # test that mutable properties can be updated
        upd_mutable = [{
            "op": "replace",
            "path": "/string_mutable",
            "value": "new_value"
        }]
        updated_af = self.patch(url, upd_mutable)
        self.assertEqual("new_value", updated_af["string_mutable"])
        # test cannot update deactivated artifact
        upd_mutable[0]["value"] = "another_new_value"
        self.deactivate_with_admin(private_art['id'])
        # test that nobody(even admin) can publish deactivated artifact
        self.set_user("admin")
        self.patch(url, self.make_public, 400)
        self.set_user("user1")
        self.patch(url, upd_mutable, 403)
        self.activate_with_admin(private_art['id'])
        # publish artifact
        self.publish_with_admin(private_art['id'])
        # check we cannot update public artifact anymore
        self.patch(url, upd_mutable, status=403)
        self.patch(url, upd_mutable, status=403)
        # check that admin can update public artifact
        self.set_user("admin")
        self.patch(url, upd_mutable)

    def test_artifact_delete(self):
        # try ro delete not existing artifact
        url = '/sample_artifact/111111'
        self.delete(url=url, status=404)

        # check that we can delete artifact with soft dependency
        art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        artd = self.create_artifact(
            data={"name": "test_afd", "string_required": "test_str",
                  "version": "0.0.1",
                  "dependency1": '/artifacts/sample_artifact/%s' % art['id']})

        url = '/sample_artifact/%s' % artd['id']
        self.delete(url=url, status=204)

        # try to change status of artifact to deleting
        url = '/sample_artifact/%s' % art['id']
        patch = [{'op': 'replace',
                  'value': 'deleting',
                  'path': '/status'}]
        self.patch(url=url, data=patch, status=400)

        # delete artifact via different user (non admin)
        self.set_user('user2')
        self.delete(url=url, status=404)

        # delete artifact via admin user
        self.set_user('admin')
        self.delete(url=url, status=204)

        # delete public artifact via different user
        self.set_user('user1')
        art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        url = '/sample_artifact/%s' % art['id']
        self.patch(url=url, data=self.make_active)
        self.publish_with_admin(art['id'])
        self.set_user('user2')
        self.delete(url=url, status=403)

        self.set_user('user1')
        self.delete(url=url, status=403)
        self.set_user('admin')
        self.delete(url=url)

        # delete deactivated artifact
        art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        url = '/sample_artifact/%s' % art['id']
        self.patch(url=url, data=self.make_active)
        self.patch(url=url, data=self.make_deactivated)
        self.delete(url=url, status=204)

    def test_artifact_deactivate(self):
        # test artifact deactivate for non-active artifact
        private_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        url = '/sample_artifact/%s' % private_art['id']
        self.deactivate_with_admin(private_art['id'], 400)
        self.patch(url, self.make_active)
        self.set_user('admin')
        # test cannot deactivate if there is something else in request
        incorrect = self.make_deactivated + [{"op": "replace",
                                              "path": "/name",
                                              "value": "test"}]
        self.patch(url, incorrect, 400)
        self.set_user('user1')
        # test artifact deactivate success
        deactive_art = self.deactivate_with_admin(private_art['id'])
        self.assertEqual("deactivated", deactive_art["status"])
        # test deactivate is idempotent
        self.patch(url, self.make_deactivated)

    def test_artifact_reactivate(self):
        self.set_user('admin')
        private_art = self.create_artifact(
            data={"name": "test_af", "string_required": "test_str",
                  "version": "0.0.1"})
        url = '/sample_artifact/%s' % private_art['id']
        self.patch(url, self.make_active)
        self.deactivate_with_admin(private_art['id'])
        # test cannot reactivate if there is something else in request
        incorrect = self.make_active + [{"op": "replace",
                                         "path": "/name",
                                         "value": "test"}]
        self.patch(url, incorrect, 400)
        # test artifact reactivate success
        deactive_art = self.patch(url, self.make_active)
        self.assertEqual("active", deactive_art["status"])

    def test_upload_blob(self):
        # create artifact with blob
        data = 'data'
        self.create_artifact(
            data={'name': 'test_af', 'blob': data,
                  'version': '0.0.1'}, status=400)
        art = self.create_artifact(data={'name': 'test_af',
                                         'version': '0.0.1',
                                         'string_required': 'test'})
        url = '/sample_artifact/%s' % art['id']
        headers = {'Content-Type': 'application/octet-stream'}

        # upload to non-existing property
        self.put(url=url + '/blob_non_exist', data=data, status=400,
                 headers=headers)

        # upload too big value
        big_data = "this is the smallest big data"
        self.put(url=url + '/small_blob', data=big_data, status=413,
                 headers=headers)
        # upload correct blob value
        self.put(url=url + '/small_blob', data=big_data[:2], headers=headers)

        # Upload artifact via different user
        self.set_user('user2')
        self.put(url=url + '/blob', data=data, status=404,
                 headers=headers)

        # Upload file to the artifact
        self.set_user('user1')
        art = self.put(url=url + '/blob', data=data, status=200,
                       headers=headers)
        self.assertEqual('active', art['blob']['status'])
        self.assertEqual('application/octet-stream',
                         art['blob']['content_type'])
        self.assertNotIn('url', art['blob'])
        self.assertNotIn('id', art['blob'])

        # reUpload file to artifact
        self.put(url=url + '/blob', data=data, status=409,
                 headers=headers)
        # upload blob dict
        self.put(url + '/dict_of_blobs/test_key', data=data, headers=headers)
        # test re-upload failed
        self.put(url + '/dict_of_blobs/test_key', data=data, headers=headers,
                 status=409)

        # upload few other blobs to the dict
        for elem in ('aaa', 'bbb', 'ccc', 'ddd'):
            self.put(url + '/dict_of_blobs/' + elem, data=data,
                     headers=headers)

        # upload to active artifact
        self.patch(url, self.make_active)
        self.put(url + '/dict_of_blobs/key2', data=data, status=403,
                 headers=headers)

        self.delete(url)

    def test_download_blob(self):
        data = 'data'
        art = self.create_artifact(data={'name': 'test_af',
                                         'version': '0.0.1'})
        url = '/sample_artifact/%s' % art['id']

        # download not uploaded blob
        self.get(url=url + '/blob', status=400)

        # download blob from not existing artifact
        self.get(url=url + '1/blob', status=404)

        # download blob from undefined property
        self.get(url=url + '/not_a_blob', status=400)

        headers = {'Content-Type': 'application/octet-stream'}
        art = self.put(url=url + '/blob', data=data, status=200,
                       headers=headers)
        self.assertEqual('active', art['blob']['status'])

        blob_data = self.get(url=url + '/blob')
        self.assertEqual(data, blob_data)

        # download artifact via admin
        self.set_user('admin')
        blob_data = self.get(url=url + '/blob')
        self.assertEqual(data, blob_data)

        # try to download blob via different user
        self.set_user('user2')
        self.get(url=url + '/blob', status=404)

    def test_artifact_validators(self):
        data = {'name': 'test_af',
                'version': '0.0.1',
                'list_validators': ['a', 'b', 'c'],
                'dict_validators': {'abc': 'a', 'def': 'b'}}
        art = self.create_artifact(data=data)
        url = '/sample_artifact/%s' % art['id']

        # max string length is 255
        patch = [{"op": "replace", "path": "/str1", "value": 'd' * 256}]
        self.patch(url=url, data=patch, status=400)

        # test list has 3 elements maximum
        patch = [{"op": "add", "path": "/list_validators/-", "value": 'd'}]
        self.patch(url=url, data=patch, status=400)

        patch = [{"op": "replace", "path": "/list_validators",
                  "value": ['a', 'b', 'c', 'd']}]
        self.patch(url=url, data=patch, status=400)

        # test list values are unique
        patch = [{"op": "replace", "path": "/list_validators/2", "value": 'b'}]
        self.patch(url=url, data=patch, status=400)

        patch = [{"op": "replace", "path": "/list_validators",
                  "value": ['a', 'b', 'b']}]
        self.patch(url=url, data=patch, status=400)

        # regular update works
        patch = [{"op": "replace", "path": "/list_validators/1", "value": 'd'}]
        af = self.patch(url=url, data=patch)
        self.assertEqual(af['list_validators'], ['a', 'd', 'c'])

        patch = [{"op": "replace", "path": "/list_validators",
                  "value": ['c', 'b', 'a']}]
        af = self.patch(url=url, data=patch)
        self.assertEqual(af['list_validators'], ['c', 'b', 'a'])

        # test adding wrong key to dict
        patch = [{"op": "add", "path": "/dict_validators/aaa", "value": 'b'}]
        self.patch(url=url, data=patch, status=400)

        patch = [{"op": "replace", "path": "/dict_validators",
                  "value": {'abc': 'a', 'def': 'b', 'aaa': 'c'}}]
        self.patch(url=url, data=patch, status=400)

        # test dict has 3 elements maximum
        patch = [{"op": "add", "path": "/dict_validators/ghi", "value": 'd'}]
        self.patch(url=url, data=patch)

        patch = [{"op": "add", "path": "/dict_validators/jkl", "value": 'd'}]
        self.patch(url=url, data=patch, status=400)

        patch = [{"op": "replace", "path": "/dict_validators",
                  "value": {'abc': 'a', 'def': 'b', 'ghi': 'c', 'jkl': 'd'}}]
        self.patch(url=url, data=patch, status=400)

        # regular update works
        patch = [{"op": "replace", "path": "/dict_validators/abc",
                  "value": "q"}]
        af = self.patch(url=url, data=patch)
        self.assertEqual(af['dict_validators'],
                         {'abc': 'q', 'def': 'b', 'ghi': 'd'})

        patch = [{"op": "replace", "path": "/dict_validators",
                  "value": {'abc': 'l', 'def': 'x', 'ghi': 'z'}}]
        af = self.patch(url=url, data=patch)
        self.assertEqual(af['dict_validators'],
                         {'abc': 'l', 'def': 'x', 'ghi': 'z'})

    def test_artifact_field_updates(self):
        pass

    def test_schemas(self):
        schema_sample_artifact = {
            u'sample_artifact': {
                u'name': u'sample_artifact',
                u'properties': {
                    u'activated_at': {u'filter_ops': [u'eq',
                                                      u'neq',
                                                      u'in',
                                                      u'gt',
                                                      u'gte',
                                                      u'lt',
                                                      u'lte'],
                                      u'format': u'date-time',
                                      u'readOnly': True,
                                      u'required_on_activate': False,
                                      u'sortable': True,
                                      u'type': [u'string',
                                                u'null']},
                    u'blob': {u'additionalProperties': False,
                              u'filter_ops': [],
                              u'mutable': True,
                              u'properties': {u'checksum': {
                                  u'type': [u'string',
                                            u'null']},
                                  u'content_type': {
                                      u'type': u'string'},
                                  u'external': {
                                      u'type': u'boolean'},
                                  u'size': {
                                      u'type': [
                                          u'number',
                                          u'null']},
                                  u'status': {
                                      u'enum': [
                                          u'saving',
                                          u'active',
                                          u'pending_delete'],
                                      u'type': u'string'}},
                              u'required': [u'size',
                                            u'checksum',
                                            u'external',
                                            u'status',
                                            u'content_type'],
                              u'required_on_activate': False,
                              u'type': [u'object',
                                        u'null']},
                    u'bool1': {u'default': False,
                               u'filter_ops': [u'eq'],
                               u'required_on_activate': False,
                               u'type': [u'string',
                                         u'null']},
                    u'bool2': {u'default': False,
                               u'filter_ops': [u'eq'],
                               u'required_on_activate': False,
                               u'type': [u'string',
                                         u'null']},
                    u'created_at': {u'filter_ops': [u'eq',
                                                    u'neq',
                                                    u'in',
                                                    u'gt',
                                                    u'gte',
                                                    u'lt',
                                                    u'lte'],
                                    u'format': u'date-time',
                                    u'readOnly': True,
                                    u'sortable': True,
                                    u'type': u'string'},
                    u'dependency1': {u'filter_ops': [u'eq',
                                                     u'neq',
                                                     u'in'],
                                     u'required_on_activate': False,
                                     u'type': [u'string',
                                               u'null']},
                    u'dependency2': {u'filter_ops': [u'eq',
                                                     u'neq',
                                                     u'in'],
                                     u'required_on_activate': False,
                                     u'type': [u'string',
                                               u'null']},
                    u'description': {u'default': u'',
                                     u'filter_ops': [u'eq',
                                                     u'neq',
                                                     u'in'],
                                     u'maxLength': 4096,
                                     u'mutable': True,
                                     u'required_on_activate': False,
                                     u'type': [u'string',
                                               u'null']},
                    u'dict_of_blobs': {
                        u'additionalProperties': {
                            u'additionalProperties': False,
                            u'properties': {u'checksum': {
                                u'type': [u'string',
                                          u'null']},
                                u'content_type': {
                                    u'type': u'string'},
                                u'external': {
                                    u'type': u'boolean'},
                                u'size': {
                                    u'type': [
                                        u'number',
                                        u'null']},
                                u'status': {
                                    u'enum': [
                                        u'saving',
                                        u'active',
                                        u'pending_delete'],
                                    u'type': u'string'}},
                            u'required': [u'size',
                                          u'checksum',
                                          u'external',
                                          u'status',
                                          u'content_type'],
                            u'type': [u'object',
                                      u'null']},
                        u'default': {},
                        u'filter_ops': [],
                        u'maxProperties': 255,
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'dict_of_int': {
                        u'additionalProperties': {
                            u'type': u'string'},
                        u'default': {},
                        u'filter_ops': [u'eq'],
                        u'maxProperties': 255,
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'dict_of_str': {
                        u'additionalProperties': {
                            u'type': u'string'},
                        u'default': {},
                        u'filter_ops': [u'eq'],
                        u'maxProperties': 255,
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'dict_validators': {
                        u'additionalProperties': False,
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in'],
                        u'maxProperties': 3,
                        u'properties': {
                            u'abc': {u'type': [u'string',
                                               u'null']},
                            u'def': {u'type': [u'string',
                                               u'null']},
                            u'ghi': {u'type': [u'string',
                                               u'null']},
                            u'jkl': {u'type': [u'string',
                                               u'null']}},
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'float1': {u'filter_ops': [u'eq',
                                                u'neq',
                                                u'in',
                                                u'gt',
                                                u'gte',
                                                u'lt',
                                                u'lte'],
                                u'required_on_activate': False,
                                u'sortable': True,
                                u'type': [u'number',
                                          u'null']},
                    u'float2': {u'filter_ops': [u'eq',
                                                u'neq',
                                                u'in',
                                                u'gt',
                                                u'gte',
                                                u'lt',
                                                u'lte'],
                                u'required_on_activate': False,
                                u'sortable': True,
                                u'type': [u'number',
                                          u'null']},
                    u'icon': {u'additionalProperties': False,
                              u'filter_ops': [],
                              u'properties': {u'checksum': {
                                  u'type': [u'string',
                                            u'null']},
                                  u'content_type': {
                                      u'type': u'string'},
                                  u'external': {
                                      u'type': u'boolean'},
                                  u'size': {
                                      u'type': [
                                          u'number',
                                          u'null']},
                                  u'status': {
                                      u'enum': [
                                          u'saving',
                                          u'active',
                                          u'pending_delete'],
                                      u'type': u'string'}},
                              u'required': [u'size',
                                            u'checksum',
                                            u'external',
                                            u'status',
                                            u'content_type'],
                              u'required_on_activate': False,
                              u'type': [u'object',
                                        u'null']},
                    u'id': {u'filter_ops': [u'eq',
                                            u'neq',
                                            u'in'],
                            u'maxLength': 255,
                            u'pattern': u'^([0-9a-fA-F]){8}-([0-9a-fA-F]){4}-'
                                        u'([0-9a-fA-F]){4}-([0-9a-fA-F]){4}-'
                                        u'([0-9a-fA-F]){12}$',
                            u'readOnly': True,
                            u'sortable': True,
                            u'type': u'string'},
                    u'int1': {u'filter_ops': [u'eq',
                                              u'neq',
                                              u'in',
                                              u'gt',
                                              u'gte',
                                              u'lt',
                                              u'lte'],
                              u'required_on_activate': False,
                              u'sortable': True,
                              u'type': [u'integer',
                                        u'null']},
                    u'int2': {u'filter_ops': [u'eq',
                                              u'neq',
                                              u'in',
                                              u'gt',
                                              u'gte',
                                              u'lt',
                                              u'lte'],
                              u'required_on_activate': False,
                              u'sortable': True,
                              u'type': [u'integer',
                                        u'null']},
                    u'license': {u'filter_ops': [u'eq',
                                                 u'neq',
                                                 u'in'],
                                 u'maxLength': 255,
                                 u'required_on_activate': False,
                                 u'type': [u'string',
                                           u'null']},
                    u'license_url': {u'filter_ops': [u'eq',
                                                     u'neq',
                                                     u'in'],
                                     u'maxLength': 255,
                                     u'required_on_activate': False,
                                     u'type': [u'string',
                                               u'null']},
                    u'list_of_int': {u'default': [],
                                     u'filter_ops': [u'eq'],
                                     u'items': {
                                         u'type': u'string'},
                                     u'maxItems': 255,
                                     u'required_on_activate': False,
                                     u'type': [u'array',
                                               u'null']},
                    u'list_of_str': {u'default': [],
                                     u'filter_ops': [u'eq'],
                                     u'items': {
                                         u'type': u'string'},
                                     u'maxItems': 255,
                                     u'required_on_activate': False,
                                     u'type': [u'array',
                                               u'null']},
                    u'list_validators': {u'default': [],
                                         u'filter_ops': [
                                             u'eq',
                                             u'neq',
                                             u'in'],
                                         u'items': {
                                             u'type': u'string'},
                                         u'maxItems': 3,
                                         u'required_on_activate': False,
                                         u'type': [u'array',
                                                   u'null'],
                                         u'unique': True},
                    u'metadata': {u'additionalProperties': {
                        u'type': u'string'},
                        u'default': {},
                        u'filter_ops': [u'eq',
                                        u'neq'],
                        u'maxProperties': 255,
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'name': {u'filter_ops': [u'eq',
                                              u'neq',
                                              u'in'],
                              u'maxLength': 255,
                              u'required_on_activate': False,
                              u'sortable': True,
                              u'type': u'string'},
                    u'owner': {u'filter_ops': [u'eq',
                                               u'neq',
                                               u'in'],
                               u'maxLength': 255,
                               u'readOnly': True,
                               u'required_on_activate': False,
                               u'sortable': True,
                               u'type': u'string'},
                    u'provided_by': {
                        u'additionalProperties': False,
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in'],
                        u'maxProperties': 255,
                        u'properties': {
                            u'company': {u'type': u'string'},
                            u'href': {u'type': u'string'},
                            u'name': {u'type': u'string'}},
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'release': {u'default': [],
                                 u'filter_ops': [u'eq',
                                                 u'neq',
                                                 u'in'],
                                 u'items': {
                                     u'type': u'string'},
                                 u'maxItems': 255,
                                 u'required_on_activate': False,
                                 u'type': [u'array',
                                           u'null'],
                                 u'unique': True},
                    u'small_blob': {
                        u'additionalProperties': False,
                        u'filter_ops': [],
                        u'mutable': True,
                        u'properties': {
                            u'checksum': {u'type': [u'string',
                                                    u'null']},
                            u'content_type': {
                                u'type': u'string'},
                            u'external': {
                                u'type': u'boolean'},
                            u'size': {u'type': [u'number',
                                                u'null']},
                            u'status': {u'enum': [u'saving',
                                                  u'active',
                                                  u'pending_delete'],
                                        u'type': u'string'}},
                        u'required': [u'size',
                                      u'checksum',
                                      u'external',
                                      u'status',
                                      u'content_type'],
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'status': {u'default': u'queued',
                                u'enum': [u'queued',
                                          u'active',
                                          u'deactivated',
                                          u'deleted'],
                                u'filter_ops': [u'eq',
                                                u'neq',
                                                u'in'],
                                u'sortable': True,
                                u'type': u'string'},
                    u'str1': {u'filter_ops': [u'eq',
                                              u'neq',
                                              u'in',
                                              u'gt',
                                              u'gte',
                                              u'lt',
                                              u'lte'],
                              u'maxLength': 255,
                              u'required_on_activate': False,
                              u'sortable': True,
                              u'type': [u'string',
                                        u'null']},
                    u'string_mutable': {u'filter_ops': [u'eq',
                                                        u'neq',
                                                        u'in',
                                                        u'gt',
                                                        u'gte',
                                                        u'lt',
                                                        u'lte'],
                                        u'maxLength': 255,
                                        u'mutable': True,
                                        u'required_on_activate': False,
                                        u'type': [u'string',
                                                  u'null']},
                    u'string_required': {
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in',
                                        u'gt',
                                        u'gte',
                                        u'lt',
                                        u'lte'],
                        u'maxLength': 255,
                        u'type': [u'string',
                                  u'null']},
                    u'string_validators': {
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in',
                                        u'gt',
                                        u'gte',
                                        u'lt',
                                        u'lte'],
                        u'maxLength': 10,
                        u'required_on_activate': False,
                        u'type': [u'string',
                                  u'null']},
                    u'supported_by': {
                        u'additionalProperties': {
                            u'type': u'string'},
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in'],
                        u'maxProperties': 255,
                        u'required': [u'name'],
                        u'required_on_activate': False,
                        u'type': [u'object',
                                  u'null']},
                    u'system_attribute': {
                        u'default': u'default',
                        u'filter_ops': [u'eq',
                                        u'neq',
                                        u'in'],
                        u'maxLength': 255,
                        u'readOnly': True,
                        u'sortable': True,
                        u'type': [u'string',
                                  u'null']},
                    u'tags': {u'default': [],
                              u'filter_ops': [u'eq',
                                              u'neq',
                                              u'in'],
                              u'items': {u'type': u'string'},
                              u'maxItems': 255,
                              u'mutable': True,
                              u'required_on_activate': False,
                              u'type': [u'array',
                                        u'null']},
                    u'updated_at': {u'filter_ops': [u'eq',
                                                    u'neq',
                                                    u'in',
                                                    u'gt',
                                                    u'gte',
                                                    u'lt',
                                                    u'lte'],
                                    u'format': u'date-time',
                                    u'readOnly': True,
                                    u'sortable': True,
                                    u'type': u'string'},
                    u'version': {u'default': u'0.0.0',
                                 u'filter_ops': [u'eq',
                                                 u'neq',
                                                 u'in',
                                                 u'gt',
                                                 u'gte',
                                                 u'lt',
                                                 u'lte'],
                                 u'pattern': u'/^([0-9]+)\\.([0-9]+)\\.'
                                             u'([0-9]+)(?:-([0-9A-Za-z-]+'
                                             u'(?:\\.[0-9A-Za-z-]+)*))?'
                                             u'(?:\\+[0-9A-Za-z-]+)?$/',
                                 u'required_on_activate': False,
                                 u'sortable': True,
                                 u'type': u'string'},
                    u'visibility': {u'default': u'private',
                                    u'filter_ops': [u'eq'],
                                    u'maxLength': 255,
                                    u'sortable': True,
                                    u'type': u'string'}},
                u'required': [u'name'],
                u'title': u'Artifact type sample_artifact of version 1.0',
                u'type': u'object'}}

        # Get list schemas of artifacts
        result = self.get(url='/schemas')
        self.assertEqual({u'schemas': schema_sample_artifact}, result)

        # Get schema of sample_artifact
        result = self.get(url='/schemas/sample_artifact')
        self.assertEqual({u'schemas': schema_sample_artifact}, result)

        # Validation of schemas
        result = self.get(url='/schemas')['schemas']
        for artifact_type, schema in result.items():
            jsonschema.Draft4Validator.check_schema(schema)

    def test_artifact_sorted(self):
        art_list = [self.create_artifact({'name': 'name%s' % i,
                                          'version': '1.0',
                                          'tags': ['tag%s' % i],
                                          'int1': i,
                                          'float1': 123.456 + (-0.9) ** i,
                                          'str1': 'bugaga',
                                          'bool1': True,
                                          'list_of_int': [11, 22, - i],
                                          'dict_of_int': {'one': 4 * i,
                                                          'two': (-2) ** i}})
                    for i in range(5)]

        # sorted by string 'asc'
        url = '/sample_artifact?sort=name:asc'
        result = self.get(url=url)
        expected = sort_results(art_list)
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by string 'desc'
        url = '/sample_artifact?sort=name:desc'
        result = self.get(url=url)
        expected = sort_results(art_list)
        expected.reverse()
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by int 'asc'
        url = '/sample_artifact?sort=int1:asc'
        result = self.get(url=url)
        expected = sort_results(art_list, target='int1')
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by int 'desc'
        url = '/sample_artifact?sort=int1:desc'
        result = self.get(url=url)
        expected = sort_results(art_list, target='int1')
        expected.reverse()
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by float 'asc'
        url = '/sample_artifact?sort=float1:asc'
        result = self.get(url=url)
        expected = sort_results(art_list, target='float1')
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by float 'desc'
        url = '/sample_artifact?sort=float1:desc'
        result = self.get(url=url)
        expected = sort_results(art_list, target='float1')
        expected.reverse()
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by unsorted 'asc'
        url = '/sample_artifact?sort=bool1:asc'
        self.get(url=url, status=400)

        # sorted by unsorted 'desc'
        url = '/sample_artifact?sort=bool1:desc'
        self.get(url=url, status=400)

        # sorted by non-existent 'asc'
        url = '/sample_artifact?sort=non_existent:asc'
        self.get(url=url, status=400)

        # sorted by non-existent 'desc'
        url = '/sample_artifact?sort=non_existent:desc'
        self.get(url=url, status=400)

        # sorted by invalid op
        url = '/sample_artifact?sort=name:invalid_op'
        self.get(url=url, status=400)

        # sorted without op
        url = '/sample_artifact?sort=name'
        result = self.get(url=url)
        expected = sort_results(art_list)
        expected.reverse()
        self.assertEqual(expected, result['sample_artifact'])

        # sorted by list
        url = '/sample_artifact?sort=list_of_int:asc'
        self.get(url=url, status=400)

        # sorted by dict
        url = '/sample_artifact?sort=dict_of_int:asc'
        self.get(url=url, status=400)

        # sorted by element of dict
        url = '/sample_artifact?sort=dict_of_int.one:asc'
        self.get(url=url, status=400)

        # sorted by any prop
        url = '/sample_artifact?sort=name:asc,int1:desc'
        result = self.get(url=url)
        expected = sort_results(sort_results(art_list), target='int1')
        self.assertEqual(expected, result['sample_artifact'])

    def test_artifact_field_dict(self):
        art1 = self.create_artifact(data={"name": "art1"})

        # create artifact without dict prop
        data = {'name': 'art_without_dict'}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual({}, result['dict_of_str'])

        # create artifact with dict prop
        data = {'name': 'art_with_dict',
                'dict_of_str': {'a': '1', 'b': '3'}}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual({'a': '1', 'b': '3'}, result['dict_of_str'])

        # create artifact with empty dict
        data = {'name': 'art_with_empty_dict',
                'dict_of_str': {}}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual({}, result['dict_of_str'])

        # add element in invalid path
        data = [{'op': 'add',
                 'path': '/dict_of_str',
                 'value': 'val1'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # add new element
        data = [{'op': 'add',
                 'path': '/dict_of_str/new',
                 'value': 'val1'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual('val1', result['dict_of_str']['new'])

        # add existent element
        data = [{'op': 'add',
                 'path': '/dict_of_str/new',
                 'value': 'val_new'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual('val_new', result['dict_of_str']['new'])

        # add element with empty key
        data = [{'op': 'add',
                 'path': '/dict_of_str/',
                 'value': 'val1'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual('val1', result['dict_of_str'][''])

        # replace element
        data = [{'op': 'replace',
                 'path': '/dict_of_str/new',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual('val2', result['dict_of_str']['new'])

        # replace non-existent element
        data = [{'op': 'replace',
                 'path': '/dict_of_str/non_exist',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # remove element
        data = [{'op': 'remove',
                 'path': '/dict_of_str/new',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertIsNone(result['dict_of_str'].get('new'))

        # remove non-existent element
        data = [{'op': 'remove',
                 'path': '/dict_of_str/non_exist',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # set value
        data = [{'op': 'add',
                 'path': '/dict_of_str',
                 'value': {'key1': 'val1', 'key2': 'val2'}}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual({'key1': 'val1', 'key2': 'val2'},
                         result['dict_of_str'])

        # replace value
        data = [{'op': 'add',
                 'path': '/dict_of_str',
                 'value': {'key11': 'val1', 'key22': 'val2'}}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual({'key11': 'val1', 'key22': 'val2'},
                         result['dict_of_str'])

        # remove value
        data = [{'op': 'add',
                 'path': '/dict_of_str',
                 'value': {}}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual({},
                         result['dict_of_str'])

        # set an element of the wrong non-conversion type value
        data = [{'op': 'add',
                 'path': '/dict_of_str/wrong_type',
                 'value': [1, 2, 4]}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # set an element of the wrong conversion type value
        data = [{'op': 'add',
                 'path': '/dict_of_str/wrong_type',
                 'value': 1}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual('1', result['dict_of_str']['wrong_type'])

        # add element with None value
        data = [{'op': 'add',
                 'path': '/dict_of_blob/nane_value',
                 'value': None}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

    def test_artifact_field_list(self):
        art1 = self.create_artifact(data={"name": "art1"})

        # create artifact without list prop
        data = {'name': 'art_without_list'}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual([], result['list_of_str'])

        # create artifact with list prop
        data = {'name': 'art_with_list',
                'list_of_str': ['a', 'b']}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual(['a', 'b'], result['list_of_str'])

        # create artifact with empty list
        data = {'name': 'art_with_empty_list',
                'list_of_str': []}
        result = self.post(url='/sample_artifact', status=201, data=data)
        self.assertEqual([], result['list_of_str'])

        # add value
        data = [{'op': 'add',
                 'path': '/list_of_str',
                 'value': ['b', 'd']}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['b', 'd'], result['list_of_str'])

        # replace value
        data = [{'op': 'replace',
                 'path': '/list_of_str',
                 'value': ['aa', 'dd']}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['aa', 'dd'], result['list_of_str'])

        # remove value
        data = [{'op': 'add',
                 'path': '/list_of_str',
                 'value': []}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual([], result['list_of_str'])

        # add new element on empty list
        self.assertEqual([], art1['list_of_str'])
        data = [{'op': 'add',
                 'path': '/list_of_str/-',
                 'value': 'val1'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val1'], result['list_of_str'])

        # add new element on index
        data = [{'op': 'add',
                 'path': '/list_of_str/0',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val2', 'val1'], result['list_of_str'])

        # add new element on next index
        data = [{'op': 'add',
                 'path': '/list_of_str/1',
                 'value': 'val3'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val2', 'val3', 'val1'], result['list_of_str'])

        # add new element on default index
        data = [{'op': 'add',
                 'path': '/list_of_str/-',
                 'value': 'val4'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val2', 'val3', 'val1', 'val4'],
                         result['list_of_str'])

        # add new element on non-existent index
        data = [{'op': 'add',
                 'path': '/list_of_str/10',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # replace element on index
        data = [{'op': 'replace',
                 'path': '/list_of_str/1',
                 'value': 'val_new'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val2', 'val_new', 'val1', 'val4'],
                         result['list_of_str'])

        # replace element on default index
        data = [{'op': 'replace',
                 'path': '/list_of_str/-',
                 'value': 'val-'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # replace new element on non-existent index
        data = [{'op': 'replace',
                 'path': '/list_of_str/99',
                 'value': 'val_new'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # remove element on index
        data = [{'op': 'remove',
                 'path': '/list_of_str/1',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        result = self.patch(url=url, data=data)
        self.assertEqual(['val2', 'val1', 'val4'], result['list_of_str'])

        # remove element on default index
        data = [{'op': 'remove',
                 'path': '/list_of_str/-',
                 'value': 'val3'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

        # remove new element on non-existent index
        data = [{'op': 'remove',
                 'path': '/list_of_str/999',
                 'value': 'val2'}]
        url = '/sample_artifact/%s' % art1['id']
        self.patch(url=url, data=data, status=400)

    def test_support_unicode(self):
        unicode_text = u'\u041f\u0420\u0418\u0412\u0415\u0422'
        art1 = self.create_artifact(data={'name': unicode_text})
        self.assertEqual(unicode_text, art1['name'])

        mixed_text = u'la\u041f'
        art2 = self.create_artifact(data={'name': mixed_text})
        self.assertEqual(mixed_text, art2['name'])

        headers = {'Content-Type': 'text/html; charset=UTF-8'}
        url = u'/sample_artifact?name=\u041f\u0420\u0418\u0412\u0415\u0422'
        response_url = u'/artifacts/sample_artifact?name=' \
                       u'%D0%9F%D0%A0%D0%98%D0%92%D0%95%D0%A2'
        result = self.get(url=url, headers=headers)
        self.assertEqual(art1, result['sample_artifact'][0])
        self.assertEqual(response_url, result['first'])
