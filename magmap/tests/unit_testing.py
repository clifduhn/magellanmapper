# MagellanMapper unit testing
# Author: David Young, 2018, 2020
"""Unit testing for the MagellanMapper package.
"""

import unittest

from magmap.io import cli
from magmap.settings import config
from magmap.io import importer

TEST_IMG = "test.czi"


class TestImageStackProcessing(unittest.TestCase):
    
    def setUp(self):
        config.filename = TEST_IMG
        config.channel = None
        cli.setup_profiles(["lightsheet_4xnuc"], None)
    
    def test_load_image(self):
        image5d = importer.read_file(
            config.filename, config.series, channel=config.channel, load=False)
        self.assertEqual(image5d.shape, (1, 51, 200, 200, 2))
    
    def test_process_whole_image(self):
        _, _, blobs = cli.process_file(
            config.filename, config.series, (30, 30, 8), (70, 70, 10))
        self.assertEqual(len(blobs), 195)


if __name__ == "__main__":
    unittest.main(verbosity=2)
