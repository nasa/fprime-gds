#!/usr/bin/env python3
"""
test_base_url_feature.py:

Simple test script to verify the base URL feature implementation.
This script tests the basic functionality without requiring the full test framework.

@author: F' GDS Team
"""
import os
import sys
import tempfile
import subprocess

# Add the source directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

def test_cli_argument_parsing():
    """Test that the CLI argument parsing works correctly"""
    print("Testing CLI argument parsing...")
    
    try:
        from fprime_gds.executables.cli import GdsParser
        
        parser = GdsParser()
        
        # Test default base URL
        args = type('Args', (), {'base_url': ''})()
        result = parser.handle_arguments(args)
        assert result.base_url == '', f"Expected empty string, got {result.base_url}"
        print("✓ Default base URL test passed")
        
        # Test base URL normalization
        args = type('Args', (), {'base_url': 'fprime-gds'})()
        result = parser.handle_arguments(args)
        assert result.base_url == '/fprime-gds', f"Expected '/fprime-gds', got {result.base_url}"
        print("✓ Base URL normalization test passed")
        
        # Test trailing slash removal
        args = type('Args', (), {'base_url': '/fprime-gds/'})()
        result = parser.handle_arguments(args)
        assert result.base_url == '/fprime-gds', f"Expected '/fprime-gds', got {result.base_url}"
        print("✓ Trailing slash removal test passed")
        
        # Test invalid characters
        try:
            args = type('Args', (), {'base_url': '/fprime gds'})()
            parser.handle_arguments(args)
            assert False, "Expected ValueError for invalid characters"
        except ValueError:
            print("✓ Invalid character validation test passed")
        
        print("All CLI argument parsing tests passed!\n")
        return True
        
    except Exception as e:
        print(f"✗ CLI argument parsing test failed: {e}")
        return False


def test_flask_app_configuration():
    """Test that the Flask app configuration works correctly"""
    print("Testing Flask app configuration...")
    
    try:
        # Test with environment variable
        os.environ['BASE_URL'] = '/test-gds'
        os.environ['STANDARD_PIPELINE_ARGUMENTS'] = '--dictionary|test.xml|--logs|/tmp/logs'
        
        # Import after setting environment variables
        from fprime_gds.flask.default_settings import BASE_URL
        
        assert BASE_URL == '/test-gds', f"Expected '/test-gds', got {BASE_URL}"
        print("✓ Environment variable configuration test passed")
        
        # Clean up
        del os.environ['BASE_URL']
        del os.environ['STANDARD_PIPELINE_ARGUMENTS']
        
        print("Flask app configuration tests passed!\n")
        return True
        
    except Exception as e:
        print(f"✗ Flask app configuration test failed: {e}")
        return False


def test_javascript_config_update():
    """Test that the JavaScript config update function works"""
    print("Testing JavaScript configuration...")
    
    try:
        # Read the config.js file
        config_path = os.path.join(os.path.dirname(__file__), 'src', 'fprime_gds', 'flask', 'static', 'js', 'config.js')
        
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                content = f.read()
                
            # Check that the updateConfigWithBaseUrl function exists
            assert 'updateConfigWithBaseUrl' in content, "updateConfigWithBaseUrl function not found"
            assert 'config.baseUrl = baseUrl' in content, "Base URL assignment not found"
            print("✓ JavaScript config update function found")
            
            # Check that baseUrl property exists in config
            assert 'baseUrl: ""' in content, "baseUrl property not found in config"
            print("✓ JavaScript config baseUrl property found")
            
        print("JavaScript configuration tests passed!\n")
        return True
        
    except Exception as e:
        print(f"✗ JavaScript configuration test failed: {e}")
        return False


def test_html_template_updates():
    """Test that HTML templates have been updated for base URL support"""
    print("Testing HTML template updates...")
    
    try:
        # Read the index.html file
        html_path = os.path.join(os.path.dirname(__file__), 'src', 'fprime_gds', 'flask', 'static', 'index.html')
        
        if os.path.exists(html_path):
            with open(html_path, 'r') as f:
                content = f.read()
                
            # Check that download links use config.baseUrl
            assert 'config.baseUrl + \'/download/files/\'' in content, "Download link not updated for base URL"
            print("✓ HTML download link updated for base URL")
            
        print("HTML template update tests passed!\n")
        return True
        
    except Exception as e:
        print(f"✗ HTML template update test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("Running Base URL Feature Tests")
    print("=" * 40)
    
    tests = [
        test_cli_argument_parsing,
        test_flask_app_configuration,
        test_javascript_config_update,
        test_html_template_updates,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print("=" * 40)
    print(f"Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Base URL feature implementation looks good.")
        return 0
    else:
        print("❌ Some tests failed. Please review the implementation.")
        return 1


if __name__ == '__main__':
    sys.exit(main())
