import tempfile, unittest
from pathlib import Path
from fastapi.testclient import TestClient
from waferai.server import create_app

class IntegrationTest(unittest.TestCase):
    def test_real_model_review_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'test.sqlite3'
            with TestClient(create_app(db_path=db)) as client:
                self.assertEqual(client.get('/').status_code,200)
                self.assertTrue(client.get('/api/status').json()['model_ready'])
                invalid=client.post('/api/predict',files={'file':('bad.json',b'[[3]]','application/json')})
                self.assertEqual(invalid.status_code,422)
                result=client.post('/api/predict',files={'file':('synthetic.json',b'[[0,1,0],[1,2,1],[0,1,0]]','application/json')})
                self.assertEqual(result.status_code,200,result.text)
                data=result.json();record_id=data['id']
                self.assertEqual(len(data['result']['probabilities']),9)
                self.assertEqual(client.post(f'/api/records/{record_id}/review',json={'label':'invalid'}).status_code,422)
                review=client.post(f'/api/records/{record_id}/review',json={'label':'Center','note':'synthetic integration test'})
                self.assertEqual(review.status_code,200,review.text)
                self.assertEqual(review.json()['reviews'][0]['label'],'Center')
                self.assertEqual(review.json()['result'],data['result'])
                client.post(f'/api/records/{record_id}/review',json={'label':'Donut','note':'second review'})
            with TestClient(create_app(db_path=db)) as client:
                detail=client.get(f'/api/records/{record_id}').json()
                self.assertEqual(len(detail['reviews']),2)
                self.assertEqual(client.get('/api/records').json()[0]['review']['label'],'Donut')
