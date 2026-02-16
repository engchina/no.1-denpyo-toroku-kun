/**
  Copyright (c) 2015, 2025, Oracle and/or its affiliates.
  Licensed under The Universal Permissive License (UPL), Version 1.0
  as shown at https://oss.oracle.com/licenses/upl/

*/

'use strict';

module.exports = function (configObj) {
  return new Promise((resolve, reject) => {
    console.log('Running before_serve hook.');

    // API proxy middleware: forward /api requests to Flask backend
    const { createProxyMiddleware } = (() => {
      try {
        return require('http-proxy-middleware');
      } catch (e) {
        return {};
      }
    })();

    if (createProxyMiddleware) {
      const apiProxy = createProxyMiddleware({
        target: 'http://localhost:5000',
        changeOrigin: true
      });
      configObj['preMiddleware'] = [
        { path: '/api', handle: apiProxy }
      ];
    }

    resolve(configObj);
  });
};
