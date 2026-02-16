/**
 * Model Info ViewModel
 * Displays model metadata, classes, and configuration
 */
define(['knockout', 'ojs/ojarraydataprovider', 'ojs/ojknockout', 'ojs/ojlabel',
        'ojs/ojbutton', 'ojs/ojtable', 'ojs/ojlistview', 'ojs/ojlistitemlayout',
        'ojs/ojprogress-circle'],
    function(ko, ArrayDataProvider) {

        function ModelInfoViewModel() {
            var self = this;

            // Model info
            this.algorithm = ko.observable('-');
            this.numClasses = ko.observable(0);
            this.nEstimators = ko.observable(0);
            this.embeddingModel = ko.observable('-');
            this.embeddingDimension = ko.observable(0);
            this.trainDate = ko.observable('-');
            this.modelVersion = ko.observable('-');

            // Class list
            this.classList = ko.observableArray([]);
            this.classListProvider = ko.computed(function() {
                return new ArrayDataProvider(self.classList(), { keyAttributes: 'name' });
            });

            // Feature details
            this.featureDetails = ko.observableArray([]);
            this.featureDetailsProvider = ko.computed(function() {
                return new ArrayDataProvider(self.featureDetails(), { keyAttributes: 'name' });
            });

            // Loading state
            this.isLoading = ko.observable(true);
            this.errorMessage = ko.observable('');

            // Fetch model info
            this.loadModelInfo = function() {
                self.isLoading(true);
                self.errorMessage('');

                fetch('/api/v1/model/info')
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;

                        self.algorithm(data.algorithm || '-');
                        self.numClasses(data.num_classes || 0);
                        self.nEstimators(data.n_estimators || 0);
                        self.embeddingModel(data.embedding_model || '-');
                        self.embeddingDimension(data.embedding_dimension || 0);
                        self.trainDate(data.train_date || '-');
                        self.modelVersion(data.model_version || '-');

                        // Build class list
                        if (data.classes) {
                            var classes = data.classes.map(function(cls, i) {
                                return { name: cls, index: i + 1 };
                            });
                            self.classList(classes);
                        }

                        // Build feature details table
                        var features = [];
                        features.push({ name: 'Algorithm', value: data.algorithm || '-' });
                        features.push({ name: 'Number of Classes', value: String(data.num_classes || 0) });
                        features.push({ name: 'Number of Estimators', value: String(data.n_estimators || 0) });
                        features.push({ name: 'Embedding Model', value: data.embedding_model || '-' });
                        features.push({ name: 'Embedding Dimension', value: String(data.embedding_dimension || 0) });
                        if (data.train_date) features.push({ name: 'Train Date', value: data.train_date });
                        if (data.model_version) features.push({ name: 'Model Version', value: data.model_version });
                        if (data.train_accuracy) features.push({ name: 'Train Accuracy', value: (data.train_accuracy * 100).toFixed(2) + '%' });
                        if (data.test_accuracy) features.push({ name: 'Test Accuracy', value: (data.test_accuracy * 100).toFixed(2) + '%' });
                        self.featureDetails(features);

                        self.isLoading(false);
                    })
                    .catch(function(err) {
                        self.errorMessage('Failed to load model info: ' + err.message);
                        self.isLoading(false);
                    });
            };

            // Refresh
            this.refresh = function() {
                self.loadModelInfo();
            };

            // Initial load
            this.loadModelInfo();
        }

        return ModelInfoViewModel;
    }
);
