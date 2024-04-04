#!/bin/bash
set -e
python3 -m pip install --upgrade pip
python3 -m pip install -e .
python3 fastapi_app/seed_data.py
python3 -m gunicorn app:app