"""
Data Aggregator — Entry Point
==============================
Run this script to execute all enabled workers.
Usage:  python run.py
"""
import os
import sys

# Ensure project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.driver import main

if __name__ == '__main__':
    main()
