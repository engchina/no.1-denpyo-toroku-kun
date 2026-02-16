/**
 * Stats ViewModel
 * Displays performance and cache statistics
 */
define(['knockout', 'ojs/ojarraydataprovider', 'ojs/ojknockout', 'ojs/ojlabel',
        'ojs/ojbutton', 'ojs/ojtable'],
    function(ko, ArrayDataProvider) {

        function StatsViewModel() {
            var self = this;

            // Performance stats
            this.totalPredictions = ko.observable(0);
            this.totalErrors = ko.observable(0);
            this.errorRate = ko.observable('-');
            this.avgPredictionTime = ko.observable('-');
            this.p95PredictionTime = ko.observable('-');
            this.p99PredictionTime = ko.observable('-');
            this.minPredictionTime = ko.observable('-');
            this.maxPredictionTime = ko.observable('-');
            this.avgEmbeddingTime = ko.observable('-');

            // Cache stats
            this.cacheHits = ko.observable(0);
            this.cacheMisses = ko.observable(0);
            this.cacheHitRate = ko.observable('-');
            this.cacheSize = ko.observable(0);
            this.cacheMaxSize = ko.observable(0);

            // Loading state
            this.isLoading = ko.observable(true);
            this.lastUpdated = ko.observable('-');

            // Intent distribution
            this.intentDistribution = ko.observableArray([]);
            this.intentDistributionProvider = ko.computed(function() {
                return new ArrayDataProvider(self.intentDistribution(), { keyAttributes: 'intent' });
            });

            // Fetch stats
            this.loadStats = function() {
                self.isLoading(true);
                fetch('/api/v1/stats')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;

                        // Performance metrics
                        if (data.performance) {
                            var perf = data.performance;
                            self.totalPredictions(perf.total_predictions || 0);
                            self.totalErrors(perf.total_errors || 0);
                            self.errorRate(((perf.error_rate || 0) * 100).toFixed(2) + '%');
                            self.avgPredictionTime((perf.avg_prediction_time || 0).toFixed(4) + 's');
                            self.p95PredictionTime((perf.p95_prediction_time || 0).toFixed(4) + 's');
                            self.p99PredictionTime((perf.p99_prediction_time || 0).toFixed(4) + 's');
                            self.minPredictionTime((perf.min_prediction_time || 0).toFixed(4) + 's');
                            self.maxPredictionTime((perf.max_prediction_time || 0).toFixed(4) + 's');
                            self.avgEmbeddingTime((perf.avg_embedding_time || 0).toFixed(4) + 's');
                        }

                        // Cache metrics
                        if (data.cache) {
                            var cache = data.cache;
                            self.cacheHits(cache.hits || 0);
                            self.cacheMisses(cache.misses || 0);
                            self.cacheHitRate(((cache.hit_rate || 0) * 100).toFixed(1) + '%');
                            self.cacheSize(cache.cache_size || 0);
                            self.cacheMaxSize(cache.max_size || 0);
                        }

                        // Intent distribution
                        if (data.performance && data.performance.intent_distribution) {
                            var dist = data.performance.intent_distribution;
                            var distList = [];
                            Object.keys(dist).forEach(function(intent) {
                                distList.push({ intent: intent, count: dist[intent] });
                            });
                            distList.sort(function(a, b) { return b.count - a.count; });
                            self.intentDistribution(distList);
                        }

                        self.lastUpdated(new Date().toLocaleTimeString());
                        self.isLoading(false);
                    })
                    .catch(function(err) {
                        console.error('Failed to load stats:', err);
                        self.isLoading(false);
                    });
            };

            // Clear cache
            this.clearCache = function() {
                fetch('/api/v1/cache/clear', { method: 'POST' })
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function() {
                        self.loadStats();
                    })
                    .catch(function(err) {
                        console.error('Cache clear failed:', err);
                    });
            };

            // Refresh
            this.refresh = function() {
                self.loadStats();
            };

            // Initial load
            this.loadStats();
        }

        return StatsViewModel;
    }
);
