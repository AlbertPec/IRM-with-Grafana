## How to run fault:

Deploy Virtual service that simulates fault:
```
kubectl -n default apply -f .\fault_scripts\request_error.yaml
```

To "fix" error delete service:
```
kubectl -n default delete -f .\fault_scripts\request_error.yaml
```