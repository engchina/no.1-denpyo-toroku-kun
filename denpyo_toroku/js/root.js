/**
 * @license
 * Copyright (c) 2024, 2026, Oracle and/or its affiliates.
 * Licensed under The Universal Permissive License (UPL), Version 1.0
 * as shown at https://oss.oracle.com/licenses/upl/
 * @ignore
 */
/**
 * Application entry point - loads core dependencies and initializes Knockout bindings
 */
require(['ojs/ojbootstrap', 'knockout', './appController', 'ojs/ojlogger', 'ojs/ojknockout',
    'ojs/ojmodule', 'ojs/ojnavigationlist', 'ojs/ojbutton', 'ojs/ojtoolbar',
    'ojs/ojmenu', 'ojs/ojdrawerpopup', 'ojs/ojconveyorbelt', 'ojs/ojtabbar',
    'ojs/ojswitcher', 'ojs/ojdefer', 'ojs/ojbindtext', 'ojs/ojbindfor-each', 'ojs/ojbindif'],
    function (Bootstrap, ko, app, Logger) {
        Bootstrap.whenDocumentReady().then(
            function() {
                function init() {
                    ko.applyBindings(app, document.getElementById('globalBody'));
                }
                if (document.body.classList.contains('oj-hybrid')) {
                    document.addEventListener("deviceready", init);
                } else {
                    init();
                }
            });
    }
);
