#!/usr/bin/env python
"""
Celery worker runner - Start this in a separate terminal to process async tasks
Run: python celery_worker.py
"""
import os
from app import app, celery

if __name__ == '__main__':
    celery.start(['worker', '--loglevel=info', '--concurrency=4'])
