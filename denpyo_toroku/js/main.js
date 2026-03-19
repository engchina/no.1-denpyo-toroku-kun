/**
 * @license
 * Copyright (c) 2024, 2026, Oracle and/or its affiliates.
 * Licensed under The Universal Permissive License (UPL), Version 1.0
 * as shown at https://oss.oracle.com/licenses/upl/
 * @ignore
 */
'use strict';

/**
 * RequireJS bootstrap for Denpyo Toroku Service
 * Uses Oracle JET CDN for all library dependencies.
 * CDN bundles-config.js (loaded before this file) defines all paths and bundles.
 * Only baseUrl needs to be set here.
 */
(function () {
    window["oj_whenReady"] = true;

    requirejs.config({
        baseUrl: 'js'
    });
}());

/**
 * Load the application entry point
 */
require(['./root']);
