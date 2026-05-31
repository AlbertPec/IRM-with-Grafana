## App deployment

Connect with kubernetes cluster and then install istio, application and grafana:
```shell
istioctl manifest apply --set profile=demo

kubectl label namespace default istio-injection=enabled

kubectl apply -f app/release/kubernetes/manifests.yaml

kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.21/samples/addons/prometheus.yaml

kubectl apply -f https://raw.githubusercontent.com/istio/istio/release-1.21/samples/addons/grafana.yaml
```

After that path grafana with:
```shell
cd deployment
./grafana_deploy.sh
```

## About .env
For now deployment requires 2 variables to be present in .env file: `GF_IRM_WEBHOOK_URL` and 
`GF_DISCORD_WEBHOOK_URL` - webhook urls for grafana cloude and discord.

