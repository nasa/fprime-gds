#!/usr/bin/env python3
"""
test_base_url.py:

Unit tests for the base URL functionality in the F' GDS.
Tests various configurations and ensures proper URL handling.

@author: F' GDS Team
"""
import os
import unittest
from unittest.mock import patch, MagicMock
import tempfile
import sys

# Add the source directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../src'))

from fprime_gds.executables.cli import GdsParser
from fprime_gds.flask.app import construct_app


class TestBaseUrlCli(unittest.TestCase):
    """Test base URL command line argument parsing and validation"""

    def setUp(self):
        self.parser = GdsParser()

    def test_default_base_url(self):
        """Test that default base URL is empty string"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': ''})())
        self.assertEqual(args.base_url, '')

    def test_valid_base_url_with_leading_slash(self):
        """Test valid base URL with leading slash"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': '/fprime-gds'})())
        self.assertEqual(args.base_url, '/fprime-gds')

    def test_valid_base_url_without_leading_slash(self):
        """Test that base URL without leading slash gets normalized"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': 'fprime-gds'})())
        self.assertEqual(args.base_url, '/fprime-gds')

    def test_base_url_trailing_slash_removal(self):
        """Test that trailing slashes are removed (except for root)"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': '/fprime-gds/'})())
        self.assertEqual(args.base_url, '/fprime-gds')

    def test_root_base_url_preserved(self):
        """Test that root base URL '/' is preserved"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': '/'})())
        self.assertEqual(args.base_url, '/')

    def test_multi_level_base_url(self):
        """Test multi-level base URL paths"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': '/app/fprime-gds'})())
        self.assertEqual(args.base_url, '/app/fprime-gds')

    def test_invalid_base_url_characters(self):
        """Test that invalid characters in base URL raise ValueError"""
        with self.assertRaises(ValueError):
            self.parser.handle_arguments(type('Args', (), {'base_url': '/fprime gds'})())

    def test_base_url_with_special_characters(self):
        """Test base URL with valid special characters"""
        args = self.parser.handle_arguments(type('Args', (), {'base_url': '/fprime-gds_v2.0'})())
        self.assertEqual(args.base_url, '/fprime-gds_v2.0')


class TestBaseUrlFlaskApp(unittest.TestCase):
    """Test Flask app configuration with base URL"""

    def setUp(self):
        # Mock the standard pipeline arguments
        self.mock_env = {
            'STANDARD_PIPELINE_ARGUMENTS': '--dictionary|test.xml|--logs|/tmp/logs'
        }

    @patch.dict(os.environ, {'BASE_URL': ''})
    @patch('fprime_gds.flask.app.components.setup_pipelined_components')
    @patch('fprime_gds.executables.cli.ParserBase.parse_args')
    def test_flask_app_default_base_url(self, mock_parse_args, mock_setup_components):
        """Test Flask app with default (empty) base URL"""
        # Mock the parser and components
        mock_parse_args.return_value = (MagicMock(), None)
        mock_setup_components.return_value = MagicMock()
        
        app, api = construct_app()
        self.assertEqual(app.config.get('BASE_URL'), '')
        self.assertEqual(app.static_url_path, '')

    @patch.dict(os.environ, {'BASE_URL': '/fprime-gds'})
    @patch('fprime_gds.flask.app.components.setup_pipelined_components')
    @patch('fprime_gds.executables.cli.ParserBase.parse_args')
    def test_flask_app_custom_base_url(self, mock_parse_args, mock_setup_components):
        """Test Flask app with custom base URL"""
        # Mock the parser and components
        mock_parse_args.return_value = (MagicMock(), None)
        mock_setup_components.return_value = MagicMock()
        
        app, api = construct_app()
        self.assertEqual(app.config.get('BASE_URL'), '/fprime-gds')
        self.assertEqual(app.static_url_path, '/fprime-gds')
        self.assertEqual(app.config.get('APPLICATION_ROOT'), '/fprime-gds')


class TestBaseUrlIntegration(unittest.TestCase):
    """Integration tests for base URL functionality"""

    @patch('fprime_gds.executables.run_deployment.launch_process')
    @patch('webbrowser.open')
    def test_browser_launch_with_base_url(self, mock_browser_open, mock_launch_process):
        """Test that browser launches with correct URL including base URL"""
        from fprime_gds.executables.run_deployment import launch_html
        
        # Mock parsed arguments
        parsed_args = MagicMock()
        parsed_args.gui_addr = '127.0.0.1'
        parsed_args.gui_port = '5000'
        parsed_args.base_url = '/fprime-gds'
        
        # Mock the launch_process to return a mock process
        mock_process = MagicMock()
        mock_launch_process.return_value = mock_process
        
        # Mock StandardPipelineParser
        with patch('fprime_gds.executables.run_deployment.StandardPipelineParser') as mock_parser:
            mock_parser.return_value.reproduce_cli_args.return_value = []
            
            launch_html(parsed_args)
            
            # Verify browser was opened with correct URL
            mock_browser_open.assert_called_once()
            called_url = mock_browser_open.call_args[0][0]
            self.assertEqual(called_url, 'http://127.0.0.1:5000/fprime-gds/')

    @patch('fprime_gds.executables.run_deployment.launch_process')
    @patch('webbrowser.open')
    def test_browser_launch_without_base_url(self, mock_browser_open, mock_launch_process):
        """Test that browser launches with correct URL without base URL"""
        from fprime_gds.executables.run_deployment import launch_html
        
        # Mock parsed arguments
        parsed_args = MagicMock()
        parsed_args.gui_addr = '127.0.0.1'
        parsed_args.gui_port = '5000'
        parsed_args.base_url = ''
        
        # Mock the launch_process to return a mock process
        mock_process = MagicMock()
        mock_launch_process.return_value = mock_process
        
        # Mock StandardPipelineParser
        with patch('fprime_gds.executables.run_deployment.StandardPipelineParser') as mock_parser:
            mock_parser.return_value.reproduce_cli_args.return_value = []
            
            launch_html(parsed_args)
            
            # Verify browser was opened with correct URL
            mock_browser_open.assert_called_once()
            called_url = mock_browser_open.call_args[0][0]
            self.assertEqual(called_url, 'http://127.0.0.1:5000/')


if __name__ == '__main__':
    unittest.main()
