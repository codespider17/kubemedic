import os
from dataclasses import dataclass
from functools import lru_cache

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException


@dataclass(frozen=True)
class KubernetesClients:
    core: client.CoreV1Api
    apps: client.AppsV1Api
    batch: client.BatchV1Api
    discovery: client.DiscoveryV1Api


@lru_cache
def get_kubernetes_clients() -> KubernetesClients:
    try:
        config.load_incluster_config()
    except ConfigException:
        kubeconfig = os.getenv("KUBECONFIG", "/root/.kube/config")
        config.load_kube_config(config_file=kubeconfig)

    return KubernetesClients(
        core=client.CoreV1Api(),
        apps=client.AppsV1Api(),
        batch=client.BatchV1Api(),
        discovery=client.DiscoveryV1Api(),
    )
