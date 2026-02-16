/**
 * 予測 ViewModel
 * 単一/一括テキストの意図予測を処理
 */
define(['knockout', 'ojs/ojarraydataprovider', 'ojs/ojknockout', 'ojs/ojlabel',
        'ojs/ojinputtext', 'ojs/ojtextarea', 'ojs/ojbutton', 'ojs/ojtable', 'ojs/ojselectsingle',
        'ojs/ojformlayout', 'ojs/ojmessages', 'ojs/ojslider', 'ojs/ojprogress-circle'],
    function(ko, ArrayDataProvider) {

        function PredictViewModel() {
            var self = this;

            // 入力
            this.inputText = ko.observable('');
            this.batchTexts = ko.observable('');
            this.confidenceThreshold = ko.observable(0.5);
            this.returnProba = ko.observable(true);

            // モード: 単一または一括
            this.predictionMode = ko.observable('single');
            this.modeOptions = new ArrayDataProvider([
                { value: 'single', label: '単一予測' },
                { value: 'batch',  label: '一括予測' }
            ], { keyAttributes: 'value' });

            // 結果
            this.singleResult = ko.observable(null);
            this.batchResults = ko.observableArray([]);
            this.batchSummary = ko.observable(null);
            this.isLoading = ko.observable(false);
            this.errorMessage = ko.observable('');

            // 結果テーブルのデータプロバイダー
            this.resultsDataProvider = ko.computed(function() {
                return new ArrayDataProvider(self.batchResults(), { keyAttributes: 'index' });
            });

            // 単一結果の確率テーブル
            this.probabilityData = ko.observableArray([]);
            this.probabilityDataProvider = ko.computed(function() {
                return new ArrayDataProvider(self.probabilityData(), { keyAttributes: 'intent' });
            });

            // 信頼度しきい値の表示テキスト
            this.confidenceThresholdDisplay = ko.computed(function() {
                return (self.confidenceThreshold() * 100).toFixed(0) + '%';
            });

            // 信頼度の CSS クラスを取得するヘルパー
            this.getConfidenceClass = function(confidence) {
                if (confidence >= 0.7) return 'span-green';
                if (confidence >= 0.4) return 'span-yellow';
                return 'span-red';
            };

            // 信頼度ラベルを取得するヘルパー
            this.getConfidenceLabel = function(confidence) {
                if (confidence >= 0.7) return '自動処理';
                if (confidence >= 0.4) return '要確認';
                return '要エスカレーション';
            };

            // 単一予測
            this.predictSingle = function() {
                var text = self.inputText().trim();
                if (!text) {
                    self.errorMessage('予測するテキストを入力してください。');
                    return;
                }
                self.errorMessage('');
                self.isLoading(true);
                self.singleResult(null);
                self.probabilityData([]);

                var url = '/api/v1/predict/single';
                var params = new URLSearchParams({
                    text: text,
                    return_proba: self.returnProba()
                });

                fetch(url + '?' + params.toString(), { method: 'POST' })
                    .then(function(response) {
                        return response.json().then(function(body) {
                            if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                            return body;
                        });
                    })
                    .then(function(result) {
                        var data = result.data || result;
                        // 信頼度クラスとラベルを追加
                        if (data.confidence != null) {
                            data.confidenceClass = self.getConfidenceClass(data.confidence);
                            data.confidenceLabel = self.getConfidenceLabel(data.confidence);
                            data.confidenceDisplay = (data.confidence * 100).toFixed(2) + '%';
                        }
                        self.singleResult(data);

                        // 確率テーブルを構築
                        if (data.all_probabilities) {
                            var probList = [];
                            Object.keys(data.all_probabilities).forEach(function(intent) {
                                probList.push({
                                    intent: intent,
                                    probability: data.all_probabilities[intent],
                                    probabilityDisplay: (data.all_probabilities[intent] * 100).toFixed(2) + '%'
                                });
                            });
                            probList.sort(function(a, b) { return b.probability - a.probability; });
                            self.probabilityData(probList);
                        }
                        self.isLoading(false);
                    })
                    .catch(function(err) {
                        self.errorMessage('予測に失敗しました: ' + err.message);
                        self.isLoading(false);
                    });
            };

            // 一括予測
            this.predictBatch = function() {
                var rawTexts = self.batchTexts().trim();
                if (!rawTexts) {
                    self.errorMessage('テキストを入力してください（1行に1件）。');
                    return;
                }
                self.errorMessage('');
                self.isLoading(true);
                self.batchResults([]);
                self.batchSummary(null);

                var texts = rawTexts.split('\n').filter(function(t) { return t.trim() !== ''; });

                fetch('/api/v1/predict', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        texts: texts,
                        return_proba: self.returnProba(),
                        confidence_threshold: self.confidenceThreshold()
                    })
                })
                .then(function(response) {
                    return response.json().then(function(body) {
                        if (!response.ok) throw new Error((body.errorMessages && body.errorMessages[0]) || ('HTTP ' + response.status));
                        return body;
                    });
                })
                .then(function(result) {
                    var data = result.data || result;
                    self.batchSummary({
                        total: data.total,
                        processingTime: (data.processing_time || 0).toFixed(3) + '秒'
                    });

                    var rows = (data.results || []).map(function(r, i) {
                        var conf = r.confidence || 0;
                        return {
                            index: i + 1,
                            text: r.text || texts[i],
                            intent: r.intent,
                            confidence: conf,
                            confidenceDisplay: (conf * 100).toFixed(2) + '%',
                            confidenceClass: self.getConfidenceClass(conf),
                            confidenceLabel: self.getConfidenceLabel(conf)
                        };
                    });
                    self.batchResults(rows);
                    self.isLoading(false);
                })
                .catch(function(err) {
                    self.errorMessage('一括予測に失敗しました: ' + err.message);
                    self.isLoading(false);
                });
            };

            // 結果をクリア
            this.clearResults = function() {
                self.singleResult(null);
                self.batchResults([]);
                self.batchSummary(null);
                self.probabilityData([]);
                self.errorMessage('');
                self.inputText('');
                self.batchTexts('');
            };
        }

        return PredictViewModel;
    }
);
