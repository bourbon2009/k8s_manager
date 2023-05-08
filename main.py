from flask import Flask, jsonify, abort
from kubernetes import client, config, watch
from kubernetes.client.rest import ApiException

app = Flask(__name__)
config.load_kube_config()


class K8sResource:
    def __init__(self, name, api_instance, namespace):
        self.name = name
        self.namespace = namespace
        self.api_instance = api_instance

    def read(self):
        try:
            api_method_map = {
                "configmaps": (client.CoreV1Api, "read_namespaced_config_map"),
                "secrets": (client.CoreV1Api, "read_namespaced_secret"),
                "services": (client.CoreV1Api, "read_namespaced_service"),
                "ingresses": (client.NetworkingV1Api, "read_namespaced_ingress"),
                "deployments": (client.AppsV1Api, "read_namespaced_deployment"),
            }

            if self.api_instance not in api_method_map:
                abort(404)

            api_class, method_name = api_method_map[self.api_instance]
            api_instance = api_class()
            resource = getattr(api_instance, method_name)(self.name, self.namespace)
            return resource
        except ApiException as e:
            if e.status == 404:
                abort(404)
            else:
                raise

    def update_deployment_image(self, image):
        if self.api_instance != "deployments":
            abort(400, "This method can only be used with Deployment resources.")

        try:
            # 获取当前 Deployment
            current_deployment = self.read()

            # 更新镜像
            current_deployment.spec.template.spec.containers[0].image = image

            # 应用更新
            api_instance = client.AppsV1Api()
            updated_deployment = api_instance.patch_namespaced_deployment(
                name=self.name,
                namespace=self.namespace,
                body=current_deployment
            )

            # 监控 Deployment 状态
            w = watch.Watch()
            for event in w.stream(api_instance.list_namespaced_deployment, namespace=self.namespace,
                                  timeout_seconds=60):
                deployment = event['object']
                if deployment.metadata.name == self.name:
                    # 检查 Deployment 是否已成功更新
                    if deployment.status.updated_replicas == deployment.status.replicas and deployment.status.available_replicas == deployment.status.replicas:
                        w.stop()
                        return updated_deployment
                    elif deployment.status.unavailable_replicas > 0:
                        w.stop()
                        abort(500, "Failed to update the Deployment image.")
        except ApiException as e:
            abort(e.status)

class ConfigMap(K8sResource):
    def __init__(self, name, namespace):
        super().__init__(name, "configmaps", namespace)


class Secret(K8sResource):
    def __init__(self, name, namespace):
        super().__init__(name, "secrets", namespace)


class Service(K8sResource):
    def __init__(self, name, namespace):
        super().__init__(name, "services", namespace)


class Ingress(K8sResource):
    def __init__(self, name, namespace):
        super().__init__(name, "ingresses", namespace)


class Deployment(K8sResource):
    def __init__(self, name, namespace):
        super().__init__(name, "deployments", namespace)


resources = {
    "configmap": ConfigMap,
    "secret": Secret,
    "service": Service,
    "ingress": Ingress,
    "deployment": Deployment
}


@app.route("/<string:resource_type>/<string:name>", methods=["GET"])
def resource(resource_type, name):
    ResourceClass = resources.get(resource_type)
    if not ResourceClass:
        abort(404)
    namespace = "default"
    resource = ResourceClass(name, namespace)
    return jsonify(resource.read().to_dict())


if __name__ == "__main__":
    app.run(debug=True)
