#!/usr/bin/env python3
"""
base_url_example.py:

Example script demonstrating how to use the base URL feature with F´ GDS.
This script shows different ways to configure and use the base URL functionality.

@author: F´ GDS Team
"""
import os
import sys
import subprocess
import time
import webbrowser
from pathlib import Path


def run_gds_with_base_url(base_url, port=5000, deployment_path=None):
    """
    Run the F´ GDS with a specified base URL
    
    Args:
        base_url: The base URL path (e.g., '/fprime-gds')
        port: Port to run the GDS on (default: 5000)
        deployment_path: Path to the deployment directory (optional)
    """
    cmd = [
        'fprime-gds',
        '--base-url', base_url,
        '--gui-port', str(port),
        '--gui-addr', '127.0.0.1'
    ]
    
    if deployment_path:
        cmd.extend(['-d', deployment_path])
    
    print(f"Starting F´ GDS with base URL: {base_url}")
    print(f"Command: {' '.join(cmd)}")
    print(f"GDS will be available at: http://127.0.0.1:{port}{base_url}/")
    print("-" * 50)
    
    try:
        # Start the GDS process
        process = subprocess.Popen(cmd)
        
        # Wait a moment for the server to start
        time.sleep(3)
        
        # Open browser to the correct URL
        url = f"http://127.0.0.1:{port}{base_url}/"
        print(f"Opening browser to: {url}")
        webbrowser.open(url)
        
        # Wait for user to stop the process
        print("Press Ctrl+C to stop the GDS...")
        process.wait()
        
    except KeyboardInterrupt:
        print("\nStopping GDS...")
        process.terminate()
        process.wait()
    except FileNotFoundError:
        print("Error: fprime-gds command not found. Make sure F´ GDS is installed.")
    except Exception as e:
        print(f"Error running GDS: {e}")


def demonstrate_multiple_instances():
    """
    Demonstrate running multiple GDS instances with different base URLs
    """
    print("Multiple GDS Instances Example")
    print("=" * 40)
    print("This example shows how to run multiple GDS instances")
    print("with different base URLs on different ports.")
    print()
    
    instances = [
        {'base_url': '/mission-1', 'port': 5001},
        {'base_url': '/mission-2', 'port': 5002},
        {'base_url': '/test-gds', 'port': 5003}
    ]
    
    processes = []
    
    try:
        for instance in instances:
            cmd = [
                'fprime-gds',
                '--base-url', instance['base_url'],
                '--gui-port', str(instance['port']),
                '--gui-addr', '127.0.0.1',
                '--no-app'  # Don't start the flight software
            ]
            
            print(f"Starting GDS instance: {instance['base_url']} on port {instance['port']}")
            process = subprocess.Popen(cmd)
            processes.append(process)
            time.sleep(2)  # Stagger the startup
        
        print("\nAll instances started!")
        print("Available URLs:")
        for instance in instances:
            url = f"http://127.0.0.1:{instance['port']}{instance['base_url']}/"
            print(f"  - {url}")
        
        print("\nPress Ctrl+C to stop all instances...")
        
        # Wait for all processes
        for process in processes:
            process.wait()
            
    except KeyboardInterrupt:
        print("\nStopping all GDS instances...")
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait()
    except Exception as e:
        print(f"Error: {e}")


def test_base_url_validation():
    """
    Test the base URL validation functionality
    """
    print("Base URL Validation Test")
    print("=" * 30)
    
    test_cases = [
        ('', 'Empty string (default)'),
        ('/fprime-gds', 'Simple path'),
        ('fprime-gds', 'Path without leading slash'),
        ('/fprime-gds/', 'Path with trailing slash'),
        ('/projects/mission-1/gds', 'Multi-level path'),
        ('/gds_v2.0', 'Path with underscore and dots'),
        ('/fprime-gds-test', 'Path with hyphens'),
    ]
    
    for base_url, description in test_cases:
        print(f"Testing: '{base_url}' ({description})")
        
        # Test the validation by importing the CLI parser
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
            from fprime_gds.executables.cli import GdsParser
            
            parser = GdsParser()
            args = type('Args', (), {'base_url': base_url})()
            result = parser.handle_arguments(args)
            
            print(f"  ✓ Normalized to: '{result.base_url}'")
            
        except Exception as e:
            print(f"  ✗ Validation failed: {e}")
        
        print()


def main():
    """
    Main function to demonstrate the base URL feature
    """
    print("F´ GDS Base URL Feature Examples")
    print("=" * 40)
    print()
    
    while True:
        print("Choose an example to run:")
        print("1. Run GDS with custom base URL")
        print("2. Test base URL validation")
        print("3. Multiple GDS instances example")
        print("4. Exit")
        print()
        
        choice = input("Enter your choice (1-4): ").strip()
        
        if choice == '1':
            base_url = input("Enter base URL (e.g., /fprime-gds): ").strip()
            if not base_url:
                base_url = '/fprime-gds'
            
            port = input("Enter port (default 5000): ").strip()
            if not port:
                port = 5000
            else:
                port = int(port)
            
            run_gds_with_base_url(base_url, port)
            
        elif choice == '2':
            test_base_url_validation()
            
        elif choice == '3':
            print("Warning: This will start multiple GDS instances.")
            confirm = input("Continue? (y/N): ").strip().lower()
            if confirm == 'y':
                demonstrate_multiple_instances()
            
        elif choice == '4':
            print("Goodbye!")
            break
            
        else:
            print("Invalid choice. Please try again.")
        
        print()


if __name__ == '__main__':
    main()
