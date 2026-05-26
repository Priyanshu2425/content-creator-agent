"""Shared kernel: the pure, render-free domain (ADR 0003).

Importable on its own with zero dependencies on backends/ or services/, so the
Builder/Validator/Resolver and plugins' render facets stay pure data (ADR 0002/0004).
"""
