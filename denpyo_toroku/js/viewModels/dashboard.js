/**
 * Dashboard ViewModel
 * Displays current service health and denpyo operation summary.
 */
define(['knockout', 'ojs/ojknockout', 'ojs/ojlabel', 'ojs/ojactioncard'],
    function(ko) {

        function DashboardViewModel() {
            var self = this;

            this.serviceStatus = ko.observable('loading');
            this.serviceStatusClass = ko.computed(function() {
                var status = self.serviceStatus();
                if (status === 'healthy') return 'span-green';
                if (status === 'warning' || status === 'unknown') return 'span-blue';
                return 'span-red';
            });

            this.statusMessage = ko.observable('-');
            this.version = ko.observable('-');
            this.totalFiles = ko.observable(0);
            this.thisMonthFiles = ko.observable(0);
            this.totalRegistrations = ko.observable(0);
            this.thisMonthRegistrations = ko.observable(0);
            this.totalCategories = ko.observable(0);
            this.activeCategories = ko.observable(0);
            this.isLoading = ko.observable(true);

            this.loadHealth = function() {
                return fetch('/api/v1/health')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;
                        self.serviceStatus(data.status || 'unknown');
                        self.statusMessage(data.message || '-');
                        self.version(data.version || '-');
                    })
                    .catch(function(err) {
                        console.error('Health check failed:', err);
                        self.serviceStatus('error');
                        self.statusMessage('サービス状態を取得できませんでした');
                    });
            };

            this.loadStats = function() {
                return fetch('/api/v1/dashboard/stats')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || {};
                        var upload = data.upload_stats || {};
                        var registration = data.registration_stats || {};
                        var category = data.category_stats || {};
                        self.totalFiles(upload.total_files || 0);
                        self.thisMonthFiles(upload.this_month || 0);
                        self.totalRegistrations(registration.total_registrations || 0);
                        self.thisMonthRegistrations(registration.this_month || 0);
                        self.totalCategories(category.total_categories || 0);
                        self.activeCategories(category.active_categories || 0);
                    })
                    .catch(function(err) {
                        console.error('Stats fetch failed:', err);
                    });
            };

            this.refresh = function() {
                self.isLoading(true);
                Promise.all([self.loadHealth(), self.loadStats()]).finally(function() {
                    self.isLoading(false);
                });
            };

            this.refresh();
        }

        return DashboardViewModel;
    }
);
