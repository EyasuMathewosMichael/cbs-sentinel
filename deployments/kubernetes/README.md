# Kubernetes deployment architecture

This directory contains the Phase 18 Kubernetes deployment architecture scaffold for SENTINEL.

Structure:

```text
deployments/kubernetes/
├── base/
└── overlays/
    ├── dev/
    ├── staging/
    └── production/
```

Included artifacts:

- Deployment: base/sentinel-deployment.yaml
- Service: base/sentinel-service.yaml
- HPA: base/sentinel-hpa.yaml
- PDB: base/sentinel-pdb.yaml
- Network policy: base/sentinel-network-policy.yaml
- Secrets: base/sentinel-secret.yaml and base/sentinel-tls-secret.yaml
- Kustomize overlays for dev, staging, and production

The base is intentionally manifest-oriented and environment-independent.
