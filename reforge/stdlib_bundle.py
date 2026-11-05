"""Importa módulos de la biblioteca estándar para que PyInstaller los empaquete.

Los parches se cargan en tiempo de ejecución, así que PyInstaller no puede ver qué
importan. Todo lo que aparece aquí está garantizado dentro del .exe (API v1).
"""
# flake8: noqa
import base64, binascii, bz2, calendar, collections, concurrent.futures, configparser, csv, ctypes
import dataclasses, datetime, difflib, email, enum, fnmatch, ftplib, functools, glob, gzip, hashlib
import heapq, hmac, html, html.parser, http.client, importlib, importlib.util, io, ipaddress
import itertools, json, locale, logging, lzma, math, mimetypes, operator, pathlib, platform
import pprint, queue, random, re, secrets, shlex, shutil, socket, sqlite3, ssl, stat, string
import struct, subprocess, tarfile, tempfile, textwrap, threading, time, traceback, typing
import unicodedata, urllib.parse, urllib.request, uuid, webbrowser, xml.dom.minidom
import xml.etree.ElementTree, zipfile, zlib

try:
    import send2trash  # papelera de reciclaje (usado por parches de limpieza)
except Exception:
    send2trash = None
