"""The four database backends and their in-memory stand-ins.

Real drivers are imported inside each class, so importing this package never needs
pymongo, neo4j, cassandra-driver or redis to be installed.
"""
