#!/usr/bin/env python3
"""Inicializa o banco de dados antes de subir o servidor."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from app import app, init_db
init_db()
print("DB initialized.")
