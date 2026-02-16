/**
 * WelcomeView - はじめに（Getting Started）ページのメイン。
 * 事前構築エージェントとカスタムフローのカードを表示。
 */
import { h } from 'preact';
import { QuickStart } from './QuickStart';
import {
  TreePine,
  LineChart,
  LayoutGrid,
  Hammer
} from 'lucide-react';

function AgentCard({
  title,
  subtitle,
  description,
  iconColorClass,
  Icon,
  ctaLabel
}: {
  title: string;
  subtitle: string;
  description: string;
  iconColorClass: string;
  Icon: any;
  ctaLabel: string;
}) {
  return (
    <div tabIndex={0} class="janusCard oj-panel oj-sm-padding-0">
      <div class="janusCard--content oj-sm-padding-7x">
        <div class="genericHeading">
          <div class="genericHeading--icon">
            <figure class={`genericIcon ${iconColorClass}`}>
              <Icon size={28} strokeWidth={2} />
            </figure>
          </div>
          <div class="genericHeading--headings">
            <h1 class="genericHeading--headings__title genericHeading--headings__title--default oj-line-clamp-1">
              {title}
            </h1>
            <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-line-clamp-1 oj-sm-margin-2x-top">
              {subtitle}
            </p>
          </div>
        </div>
        <p class="oj-typography-body-md welcomeView__paragraphStyle oj-helper-hyphens-auto">
          {description}
        </p>
        <div class="janusCard--content__ctas">
          <div style={{ width: 'fit-content' }}>
            <oj-button
              class="genericButton genericButton--callToAction oj-button oj-button-cta-chrome oj-button-text-only oj-enabled oj-default oj-complete"
            >
              <button aria-label={ctaLabel} class="oj-button-button">
                <div class="oj-button-label">
                  <span class="oj-button-text">{ctaLabel}</span>
                </div>
              </button>
            </oj-button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function WelcomeView() {
  return (
    <div id="welcomeView">
      <div class="welcomeView__main">
        {/* Page Heading */}
        <div class="genericHeading">
          <div class="genericHeading--headings">
            <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
              はじめに
            </h1>
            <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
              すぐに使える事前構築エージェントを選ぶ、テンプレートからフローをカスタマイズする、またはゼロから作成できます。
            </p>
          </div>
        </div>

        {/* Pre-built agents section */}
        <div class="genericHeading">
          <div class="genericHeading--headings">
            <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
              事前構築エージェント
            </h1>
            <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
              すぐにデプロイできる完成済みのエージェント
            </p>
          </div>
        </div>

        <div class="welcomeView__prebuiltAgentCardsContainer">
          <AgentCard
            title="ナレッジエージェント"
            subtitle="情報整理と要約"
            description="文書分析、調査支援、情報の要約/統合などの機能を備え、すぐに利用できます。追加の設定は不要です。"
            iconColorClass="genericIcon__accent3Dark"
            Icon={TreePine}
            ctaLabel="新規作成"
          />
          <AgentCard
            title="データ分析エージェント"
            subtitle="データ処理と可視化"
            description="データセット分析、レポート生成、示唆の抽出に特化したエージェントです。すぐにデプロイして活用できます。"
            iconColorClass="genericIcon__accent2Dark"
            Icon={LineChart}
            ctaLabel="新規作成"
          />
        </div>

        {/* Custom flows section */}
        <div class="genericHeading">
          <div class="genericHeading--headings">
            <h1 class="genericHeading--headings__title genericHeading--headings__title--default">
              カスタムフロー
            </h1>
            <p class="genericHeading--headings__subtitle genericHeading--headings__subtitle--default oj-sm-margin-2x-top">
              テンプレートギャラリーを使って用途に合わせたフローを作成します
            </p>
          </div>
        </div>

        <div class="welcomeView__templateGalleryCardContainer">
          <AgentCard
            title="テンプレートギャラリー"
            subtitle="カスタマイズ可能なフロー"
            description="標準テンプレートに収まらないケースに最適です。振る舞いの設計、フローの設定、ツールやデータソースとの連携が行えます。"
            iconColorClass="genericIcon__secondaryDark"
            Icon={LayoutGrid}
            ctaLabel="一覧を見る"
          />
          <AgentCard
            title="エージェントビルダー"
            subtitle="ノーコードで設計"
            description={`言語モデル、データコネクタ、API、専門エージェントなどのコンポーネントを組み合わせて、プロセスの設計・オーケストレーション・自動化を行えます（プログラミング不要）。`}
            iconColorClass="genericIcon__secondaryDark"
            Icon={Hammer}
            ctaLabel="作成を開始"
          />
        </div>
      </div>

      {/* Quick Start aside */}
      <QuickStart />
    </div>
  );
}
