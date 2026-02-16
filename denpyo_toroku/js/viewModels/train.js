/**
 * Train ViewModel
 * Handles model training: data input, validation, training execution, and results display
 * Implements features defined in features/train_production.py
 */
define(['knockout', 'ojs/ojarraydataprovider', 'ojs/ojknockout', 'ojs/ojlabel',
        'ojs/ojinputtext', 'ojs/ojtextarea', 'ojs/ojinputnumber', 'ojs/ojbutton',
        'ojs/ojtable', 'ojs/ojformlayout', 'ojs/ojprogress-circle', 'ojs/ojprogress-bar',
        'ojs/ojslider', 'ojs/ojmessages'],
    function(ko, ArrayDataProvider) {

        function TrainViewModel() {
            var self = this;

            // Training data input (JSON format)
            this.trainingDataText = ko.observable('');

            // Training parameters (defaults from features/train_production.py)
            this.testSize = ko.observable(0.15);
            this.nEstimators = ko.observable(300);
            this.learningRate = ko.observable(0.05);
            this.maxDepth = ko.observable(6);

            // Validation results
            this.validationResult = ko.observable(null);
            this.classDistribution = ko.observableArray([]);
            this.classDistributionProvider = ko.computed(function() {
                return new ArrayDataProvider(self.classDistribution(), { keyAttributes: 'label' });
            });

            // Training state
            this.isValidating = ko.observable(false);
            this.isTraining = ko.observable(false);
            this.trainingStatus = ko.observable('idle');
            this.trainingProgress = ko.observable('');
            this.trainingResults = ko.observable(null);

            // Messages
            this.errorMessage = ko.observable('');
            this.successMessage = ko.observable('');

            // Quality issues table
            this.qualityIssues = ko.observableArray([]);
            this.qualityIssuesProvider = ko.computed(function() {
                return new ArrayDataProvider(self.qualityIssues(), { keyAttributes: 'index' });
            });

            // Results details table
            this.resultsDetails = ko.observableArray([]);
            this.resultsDetailsProvider = ko.computed(function() {
                return new ArrayDataProvider(self.resultsDetails(), { keyAttributes: 'name' });
            });

            // Parse training data from textarea
            this._parseTrainingData = function() {
                var raw = self.trainingDataText().trim();
                if (!raw) return null;

                try {
                    var parsed = JSON.parse(raw);
                    if (!Array.isArray(parsed)) {
                        self.errorMessage('Training data must be a JSON array');
                        return null;
                    }
                    for (var i = 0; i < parsed.length; i++) {
                        if (!parsed[i].text || !parsed[i].label) {
                            self.errorMessage('Each item must have "text" and "label" fields (error at index ' + i + ')');
                            return null;
                        }
                    }
                    return parsed;
                } catch (e) {
                    self.errorMessage('Invalid JSON format: ' + e.message);
                    return null;
                }
            };

            // Validate data quality
            this.validateData = function() {
                self.errorMessage('');
                self.successMessage('');
                self.validationResult(null);
                self.classDistribution([]);
                self.qualityIssues([]);

                var data = self._parseTrainingData();
                if (!data) return;

                self.isValidating(true);

                fetch('/api/v1/train/validate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ training_data: data })
                })
                .then(function(response) {
                    return response.json().then(function(body) {
                        if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                        return body;
                    });
                })
                .then(function(result) {
                    var d = result.data || result;
                    self.validationResult(d);

                    // Build class distribution table
                    if (d.class_distribution) {
                        var dist = [];
                        Object.keys(d.class_distribution).forEach(function(label) {
                            dist.push({ label: label, count: d.class_distribution[label] });
                        });
                        dist.sort(function(a, b) { return b.count - a.count; });
                        self.classDistribution(dist);
                    }

                    // Build quality issues
                    if (d.issues && d.issues.length > 0) {
                        var issues = d.issues.map(function(issue, i) {
                            return { index: i + 1, description: issue };
                        });
                        self.qualityIssues(issues);
                    }

                    if (d.valid) {
                        self.successMessage('Data quality check passed (' + d.total_samples + ' samples, ' + d.num_classes + ' classes)');
                    } else {
                        self.errorMessage('Data quality issues detected. Review issues below.');
                    }

                    self.isValidating(false);
                })
                .catch(function(err) {
                    self.errorMessage('Validation failed: ' + err.message);
                    self.isValidating(false);
                });
            };

            // Start training
            this.startTraining = function() {
                self.errorMessage('');
                self.successMessage('');
                self.trainingResults(null);
                self.resultsDetails([]);

                var data = self._parseTrainingData();
                if (!data) return;

                self.isTraining(true);
                self.trainingStatus('running');
                self.trainingProgress('Starting training...');

                fetch('/api/v1/train', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        training_data: data,
                        params: {
                            test_size: self.testSize(),
                            n_estimators: self.nEstimators(),
                            learning_rate: self.learningRate(),
                            max_depth: self.maxDepth()
                        }
                    })
                })
                .then(function(response) {
                    return response.json().then(function(body) {
                        if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                        return body;
                    });
                })
                .then(function() {
                    // Start polling for status
                    self._pollTrainingStatus();
                })
                .catch(function(err) {
                    self.errorMessage('Failed to start training: ' + err.message);
                    self.isTraining(false);
                    self.trainingStatus('idle');
                });
            };

            // Poll training status
            this._pollTimer = null;
            this._pollTrainingStatus = function() {
                fetch('/api/v1/train/status')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var d = result.data || result;
                        self.trainingStatus(d.status);
                        self.trainingProgress(d.progress || '');

                        if (d.status === 'completed') {
                            self.isTraining(false);
                            self.trainingResults(d.results);
                            self._buildResultsTable(d.results);
                            self.successMessage('Training completed successfully!');
                        } else if (d.status === 'failed') {
                            self.isTraining(false);
                            self.errorMessage('Training failed: ' + (d.error || 'Unknown error'));
                        } else if (d.status === 'running') {
                            // Continue polling every 3 seconds
                            self._pollTimer = setTimeout(function() {
                                self._pollTrainingStatus();
                            }, 3000);
                        }
                    })
                    .catch(function(err) {
                        self.isTraining(false);
                        self.errorMessage('Status check failed: ' + err.message);
                    });
            };

            // Build results details table (from features/train_production.py summary)
            this._buildResultsTable = function(results) {
                if (!results) return;
                var details = [];
                details.push({ name: 'Algorithm', value: 'Gradient Boosting Classifier' });
                details.push({ name: 'Train Accuracy', value: (results.train_accuracy * 100).toFixed(2) + '%' });
                details.push({ name: 'Test Accuracy', value: (results.test_accuracy * 100).toFixed(2) + '%' });
                details.push({ name: 'Overfitting Gap', value: results.overfitting_gap.toFixed(4) });
                details.push({ name: 'Classes', value: String(results.num_classes) });
                details.push({ name: 'Estimators Used', value: String(results.n_estimators_used) });
                details.push({ name: 'Train Samples', value: String(results.train_samples) });
                details.push({ name: 'Test Samples', value: String(results.test_samples) });
                details.push({ name: 'Quality Check', value: results.quality_ok ? 'Passed' : 'Issues detected' });
                if (results.quality_issues && results.quality_issues.length > 0) {
                    details.push({ name: 'Quality Issues', value: results.quality_issues.join('; ') });
                }
                details.push({ name: 'Model Path', value: results.model_path || '-' });
                self.resultsDetails(details);
            };

            // Reload model
            this.reloadModel = function() {
                self.errorMessage('');
                self.successMessage('');

                fetch('/api/v1/model/reload', { method: 'POST' })
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var d = result.data || result;
                        self.successMessage(d.message || 'Model reloaded successfully');
                    })
                    .catch(function(err) {
                        self.errorMessage('Model reload failed: ' + err.message);
                    });
            };

            // Load sample data
            this.loadSampleData = function() {
                var sampleData = [
                    {"text": "注文の配送状況を確認したい", "label": "order_tracking"},
                    {"text": "荷物はいつ届きますか", "label": "order_tracking"},
                    {"text": "配送先を変更したい", "label": "order_tracking"},
                    {"text": "商品を返品したい", "label": "return_refund"},
                    {"text": "返金の手続きを教えてください", "label": "return_refund"},
                    {"text": "不良品が届きました", "label": "return_refund"},
                    {"text": "クーポンコードを使いたい", "label": "payment"},
                    {"text": "支払い方法を変更したい", "label": "payment"},
                    {"text": "領収書を発行してください", "label": "payment"},
                    {"text": "商品の在庫はありますか", "label": "product_inquiry"},
                    {"text": "サイズの選び方を教えてください", "label": "product_inquiry"},
                    {"text": "おすすめの商品はありますか", "label": "product_inquiry"}
                ];
                self.trainingDataText(JSON.stringify(sampleData, null, 2));
            };

            // Clear all
            this.clearAll = function() {
                self.trainingDataText('');
                self.validationResult(null);
                self.classDistribution([]);
                self.qualityIssues([]);
                self.trainingResults(null);
                self.resultsDetails([]);
                self.errorMessage('');
                self.successMessage('');
                if (self._pollTimer) {
                    clearTimeout(self._pollTimer);
                    self._pollTimer = null;
                }
            };

            // Cleanup on dispose
            this.dispose = function() {
                if (self._pollTimer) {
                    clearTimeout(self._pollTimer);
                }
            };
        }

        return TrainViewModel;
    }
);
