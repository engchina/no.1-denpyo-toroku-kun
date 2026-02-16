/**
 * Dashboard ViewModel
 * Displays service health, summary statistics, and quick actions
 */
define(['knockout', 'ojs/ojarraydataprovider', 'ojs/ojknockout', 'ojs/ojlabel',
        'ojs/ojchart', 'ojs/ojactioncard', 'ojs/ojprogress-circle'],
    function(ko, ArrayDataProvider) {

        function DashboardViewModel() {
            var self = this;

            // Service status
            this.serviceStatus = ko.observable('loading');
            this.serviceStatusClass = ko.computed(function() {
                var status = self.serviceStatus();
                if (status === 'healthy') return 'span-green';
                if (status === 'warning') return 'span-blue';
                return 'span-red';
            });

            // Health data
            this.modelLoaded = ko.observable(false);
            this.uptime = ko.observable('-');
            this.version = ko.observable('-');
            this.cacheEnabled = ko.observable(false);
            this.monitoringEnabled = ko.observable(false);

            // Stats summary
            this.totalPredictions = ko.observable(0);
            this.totalErrors = ko.observable(0);
            this.errorRate = ko.observable('0.00%');
            this.avgPredictionTime = ko.observable('-');
            this.avgEmbeddingTime = ko.observable('-');
            this.cacheHitRate = ko.observable('-');
            this.cacheSize = ko.observable('-');

            // Loading state
            this.isLoading = ko.observable(true);

            // Fetch health data
            this.loadHealth = function() {
                fetch('/api/v1/health')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;
                        self.serviceStatus(data.status || 'unknown');
                        self.modelLoaded(data.model_loaded || false);
                        self.version(data.version || '-');
                        self.cacheEnabled(data.cache_enabled || false);
                        self.monitoringEnabled(data.monitoring_enabled || false);
                        if (data.uptime_seconds) {
                            var hours = Math.floor(data.uptime_seconds / 3600);
                            var mins = Math.floor((data.uptime_seconds % 3600) / 60);
                            self.uptime(hours + 'h ' + mins + 'm');
                        }
                    })
                    .catch(function(err) {
                        console.error('Health check failed:', err);
                        self.serviceStatus('error');
                    });
            };

            // Fetch stats data
            this.loadStats = function() {
                fetch('/api/v1/stats')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;
                        if (data.performance) {
                            var perf = data.performance;
                            self.totalPredictions(perf.total_predictions || 0);
                            self.totalErrors(perf.total_errors || 0);
                            var rate = perf.error_rate || 0;
                            self.errorRate((rate * 100).toFixed(2) + '%');
                            var avg = perf.avg_prediction_time || 0;
                            self.avgPredictionTime(avg.toFixed(3) + 's');
                            var embAvg = perf.avg_embedding_time || 0;
                            self.avgEmbeddingTime(embAvg.toFixed(3) + 's');
                        }
                        if (data.cache) {
                            var cache = data.cache;
                            var hitRate = cache.hit_rate || 0;
                            self.cacheHitRate((hitRate * 100).toFixed(1) + '%');
                            self.cacheSize(cache.cache_size + '/' + cache.max_size);
                        }
                        self.isLoading(false);
                    })
                    .catch(function(err) {
                        console.error('Stats fetch failed:', err);
                        self.isLoading(false);
                    });
            };

            // Refresh all data
            this.refresh = function() {
                self.isLoading(true);
                self.loadHealth();
                self.loadStats();
            };

            // Initial load
            this.loadHealth();
            this.loadStats();
        }

        return DashboardViewModel;
    }
);
