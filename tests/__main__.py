import os
import unittest

if __name__ == '__main__':
    tests_dir = os.path.dirname(__file__)
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=tests_dir, pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
