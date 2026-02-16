/**
 * QuickStart - はじめにページの右側パネル。
 * 3 ステップとヘルプリンクを表示。
 */
import { h } from 'preact';
import { FileText } from 'lucide-react';

const steps = [
  {
    number: 1,
    title: '進め方を選ぶ',
    description: '事前構築エージェントをすぐ使う、テンプレートをカスタマイズする、またはゼロから作成します。'
  },
  {
    number: 2,
    title: '設定してデプロイ',
    description: '事前構築はすぐにデプロイできます。テンプレート/カスタムは設定が必要です。'
  },
  {
    number: 3,
    title: 'テストと改善',
    description: '実データで検証し、必要に応じて性能を最適化します。'
  }
];

export function QuickStart() {
  return (
    <div id="welcomeAside">
      <div class="genericHeading">
        <div class="genericHeading--icon">
          <figure class="genericIcon genericIcon__primaryDark">
            <FileText size={28} strokeWidth={2} />
          </figure>
        </div>
        <div class="genericHeading--headings">
          <h1 class="genericHeading--headings__title genericHeading--headings__title--default oj-line-clamp-1">
            クイックスタート
          </h1>
          <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-line-clamp-1 oj-sm-margin-2x-top">
            すぐに始められます
          </p>
        </div>
      </div>

      <div class="quickStart--steps">
        {steps.map(step => (
          <div class="quickStart--step" key={step.number}>
            <div class="quickStart--stepContainer">
              <div class="quickStart--stepNumber">{step.number}</div>
            </div>
            <div>
              <div>
                <h2 class="oj-typography-subheading-xs oj-sm-margin-2x-bottom">
                  {step.title}
                </h2>
              </div>
              <p class="oj-typography-body-md oj-text-color-secondary quickStart--paragraphStyle">
                {step.description}
              </p>
            </div>
          </div>
        ))}
      </div>

      <div>
        <p class="oj-typography-subheading-xs">お困りですか？</p>
        <ul class="quickStart--helpSourcesList">
          <li>
            <a
              href="https://customersurveys.oracle.com/ords/surveys/t/applied-ai/survey?k=agent-factory-feedback-1&sc=DDH6PILJY4"
              target="_blank"
              class="oj-typography-body-md"
              rel="noopener noreferrer"
            >
              {'\uD83D\uDCAC'} フィードバックを送る
            </a>
          </li>
          <li>
            <a
              href="https://docs.oracle.com/en/database/oracle/"
              target="_blank"
              class="oj-typography-body-md"
              rel="noopener noreferrer"
            >
              {'\uD83D\uDCDA'} ドキュメントを見る
            </a>
          </li>
        </ul>
      </div>
    </div>
  );
}
