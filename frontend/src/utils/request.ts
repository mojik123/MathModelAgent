import axios from "axios";

const defaultApiBaseUrl =
	typeof window === "undefined"
		? "http://localhost:8000"
		: `${window.location.protocol}//${window.location.hostname}:8000`;

/** 创建 axios 实例 */
const service = axios.create({
	baseURL: import.meta.env.VITE_API_BASE_URL || defaultApiBaseUrl,
	timeout: 30000,
});

/** 请求拦截器 */
service.interceptors.request.use(
	(config) => {
		return config;
	},
	(error) => {
		console.log(error);
		return Promise.reject(error);
	},
);

/** 响应拦截器 */
service.interceptors.response.use(
	(response) => {
		return response;
	},
	(error) => {
		return Promise.reject(error);
	},
);

export default service;
