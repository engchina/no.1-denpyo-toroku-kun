const path = require('path');
const HtmlWebpackPlugin = require('html-webpack-plugin');
const MiniCssExtractPlugin = require('mini-css-extract-plugin');
const { CleanWebpackPlugin } = require('clean-webpack-plugin');
const CopyWebpackPlugin = require('copy-webpack-plugin');

const isProduction = process.env.NODE_ENV === 'production';

module.exports = {
  entry: {
    main: './src/components/Index.tsx'
  },
  output: {
    path: path.resolve(__dirname, 'web'),
    filename: 'js/[name].[contenthash].js',
    publicPath: '/studio/',
    clean: true
  },
  resolve: {
    extensions: ['.tsx', '.ts', '.jsx', '.js', '.css'],
    alias: {
      'react': 'preact/compat',
      'react-dom': 'preact/compat',
      'react/jsx-runtime': 'preact/jsx-runtime'
    },
    conditionNames: ['import', 'module', 'browser', 'default']
  },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: {
          loader: 'ts-loader',
          options: {
            transpileOnly: true,
            compilerOptions: {
              module: 'esnext',
              moduleResolution: 'node'
            }
          }
        },
        exclude: /node_modules/
      },
      {
        test: /\.css$/,
        use: [
          isProduction ? MiniCssExtractPlugin.loader : 'style-loader',
          'css-loader'
        ],
        sideEffects: true
      },
      {
        test: /\.s[ac]ss$/,
        use: [
          isProduction ? MiniCssExtractPlugin.loader : 'style-loader',
          'css-loader',
          'sass-loader'
        ]
      },
      {
        test: /\.(png|jpg|gif|svg|ico)$/,
        type: 'asset/resource',
        generator: {
          filename: 'styles/images/[name][ext]'
        }
      },
      {
        test: /\.(woff|woff2|eot|ttf|otf)$/,
        type: 'asset/resource',
        generator: {
          filename: 'styles/fonts/[name][ext]'
        }
      }
    ]
  },
  plugins: [
    new CleanWebpackPlugin(),
    new HtmlWebpackPlugin({
      template: './src/index.html',
      filename: 'index.html',
      inject: 'body',
      scriptLoading: 'defer'
    }),
    ...(isProduction ? [
      new MiniCssExtractPlugin({
        filename: 'styles/[name].[contenthash].css'
      })
    ] : []),
    new CopyWebpackPlugin({
      patterns: [
        {
          from: path.resolve(__dirname, 'src/styles/images'),
          to: path.resolve(__dirname, 'web/styles/images'),
          noErrorOnMissing: true
        },
        {
          from: path.resolve(__dirname, 'node_modules/@oracle/oraclejet/dist/css/redwood'),
          to: path.resolve(__dirname, 'web/vendor/oraclejet/css/redwood'),
          noErrorOnMissing: true
        },
        {
          from: path.resolve(__dirname, 'node_modules/@oracle/oraclejet-preact/amd/Theme-redwood'),
          to: path.resolve(__dirname, 'web/vendor/oraclejet-preact/Theme-redwood'),
          noErrorOnMissing: true
        },
        {
          from: path.resolve(__dirname, 'src/vendor/iconfont'),
          to: path.resolve(__dirname, 'web/vendor/iconfont'),
          noErrorOnMissing: true
        },
        {
          from: path.resolve(__dirname, 'src/vendor/fonts'),
          to: path.resolve(__dirname, 'web/vendor/fonts'),
          noErrorOnMissing: true
        }
      ]
    })
  ],
  devServer: {
    static: {
      directory: path.resolve(__dirname, 'web')
    },
    port: 3000,
    hot: true,
    historyApiFallback: {
      rewrites: [
        { from: /^\/studio\//, to: '/index.html' },
        { from: /./, to: '/index.html' }
      ]
    },
    proxy: [
      {
        context: ['/studio/v1', '/studio/api', '/studio/logout', '/studio/register'],
        target: 'http://localhost:8080',
        changeOrigin: true
      }
    ]
  },
  optimization: {
    splitChunks: {
      chunks: 'all',
      cacheGroups: {
        vendor: {
          test: /[\\/]node_modules[\\/]/,
          name: 'vendor',
          chunks: 'all'
        }
      }
    },
    runtimeChunk: 'single'
  },
  devtool: isProduction ? 'source-map' : 'eval-source-map'
};
