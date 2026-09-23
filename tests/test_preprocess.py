import unittest
import numpy as np
import torch
from torchvision import transforms
from waferai.inference import preprocess, load_model
import cv2

class PreprocessingTests(unittest.TestCase):
    def test_matches_training_validation_transform(self):
        wm = np.array([[0,1,2,1],[1,2,0,2],[0,1,1,0]], dtype=np.uint8)
        padded = np.pad(wm, ((0,1),(0,0)))
        rgb = np.array([[0,0,0],[0,255,0],[255,255,0]], dtype=np.uint8)[
            cv2.resize(padded, (224,224), interpolation=cv2.INTER_NEAREST)]
        reference = transforms.Compose([transforms.ToPILImage(), transforms.ToTensor(),
            transforms.Normalize([.485,.456,.406],[.229,.224,.225])])(rgb)
        torch.testing.assert_close(preprocess(wm)[0], reference, rtol=0, atol=0)

    def test_rejects_invalid_maps(self):
        for wm in [[], [[3]], [[float('nan')]], np.zeros((2,2,3))]:
            with self.assertRaises(ValueError): preprocess(wm)

    def test_missing_checkpoint_stops(self):
        with self.assertRaises(FileNotFoundError): load_model('/nonexistent/model.pth')
