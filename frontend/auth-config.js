// Public deployment identifiers only. Fill from the tested Cognito app client.
window.AQUACLOUD_AUTH = Object.freeze({
  domain: "https://ap-south-1q8oaap14c.auth.ap-south-1.amazoncognito.com",
  clientId: "t59l9j6o55uhlq7e03pcis35m",
  redirectUri: "http://localhost:8000/",
  logoutUri: "http://localhost:8000/",
  apiUrl: "https://t2813qa1jl.execute-api.ap-south-1.amazonaws.com/prod",
  scopes: "openid aquacloud/read aquacloud/export"
});

