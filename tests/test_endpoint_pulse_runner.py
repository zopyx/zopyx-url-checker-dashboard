import unittest
from unittest.mock import patch, MagicMock
from endpoint_pulse import endpoint_pulse_runner
import sys

class TestEndpointPulseRunner(unittest.TestCase):
    @patch('uvicorn.run')
    @patch('argparse.ArgumentParser')
    def test_main_default_args(self, mock_argparse, mock_uvicorn_run):
        """Test that main() calls uvicorn.run with default arguments."""
        # Mock argparse
        mock_args = MagicMock()
        mock_args.host = '127.0.0.1'
        mock_args.port = 8000
        mock_args.reload = False
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = mock_args
        mock_argparse.return_value = mock_parser

        # Call the main function
        endpoint_pulse_runner.main()

        # Assert that uvicorn.run was called with the correct arguments
        mock_uvicorn_run.assert_called_once_with(
            "endpoint_pulse.app:app",
            host='127.0.0.1',
            port=8000,
            reload=False
        )

    @patch('uvicorn.run')
    @patch('argparse.ArgumentParser')
    @patch.dict('os.environ', {'ENDPOINT_PULSE_RELOAD': 'true'})
    def test_main_reload_from_env(self, mock_argparse, mock_uvicorn_run):
        """Test that main() enables reload from environment variable."""
        # Mock argparse
        mock_args = MagicMock()
        mock_args.host = '127.0.0.1'
        mock_args.port = 8000
        mock_args.reload = False
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = mock_args
        mock_argparse.return_value = mock_parser

        # Call the main function
        endpoint_pulse_runner.main()

        # Assert that uvicorn.run was called with reload=True
        mock_uvicorn_run.assert_called_once_with(
            "endpoint_pulse.app:app",
            host='127.0.0.1',
            port=8000,
            reload=True
        )

    @patch('uvicorn.run')
    @patch('argparse.ArgumentParser')
    def test_main_reload_from_cli(self, mock_argparse, mock_uvicorn_run):
        """Test that main() enables reload from the command line."""
        # Mock argparse
        mock_args = MagicMock()
        mock_args.host = '127.0.0.1'
        mock_args.port = 8000
        mock_args.reload = True
        mock_parser = MagicMock()
        mock_parser.parse_args.return_value = mock_args
        mock_argparse.return_value = mock_parser

        # Call the main function
        endpoint_pulse_runner.main()

        # Assert that uvicorn.run was called with reload=True
        mock_uvicorn_run.assert_called_once_with(
            "endpoint_pulse.app:app",
            host='127.0.0.1',
            port=8000,
            reload=True
        )

if __name__ == '__main__':
    unittest.main()