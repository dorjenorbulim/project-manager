import sys
import os

path = '/home/aloyloy/project-manager'
if path not in sys.path:
    sys.path.insert(0, path)

from app import create_app
application = create_app()
