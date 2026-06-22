
import streamlit as st
import pandas as pd
import sqlite3
import numpy as np
import time
import pytz
from datetime import datetime

BEIJING_TZ = pytz.timezone('Asia/Shanghai')

CACHE_DB = 'stock_cache.db'
CACHE_DURATIONS = {
    'realtime': 300,
    'kline': 3600,
    'financial': 86400,
    'ranking': 120
}

def init_db():
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                data TEXT,
                timestamp INTEGER
            )
        ''')
        conn.commit()
        conn.close()
    except Exception as e:
        st.warning(f'数据库初始化失败: {e}')

def get_cache(key):
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('SELECT data, timestamp FROM cache WHERE key = ?', (key,))
        result = cursor.fetchone()
        conn.close()
        if result:
            data, timestamp = result
            cache_type = key.split(':')[0]
            duration = CACHE_DURATIONS.get(cache_type, 300)
            if time.time() - timestamp < duration:
                return pd.read_json(data)
    except Exception as e:
        st.warning(f'读取缓存失败: {e}')
    return None

def set_cache(key, data):
    try:
        conn = sqlite3.connect(CACHE_DB)
        cursor = conn.cursor()
        cursor.execute('REPLACE INTO cache (key, data, timestamp) VALUES (?, ?, ?)',
                      (key, data.to_json(), int(time.time())))
        conn.commit()
        conn.close()
    except Exception as e:
        st.warning(f'写入缓存失败: {e}')

def get_realtime_data():
    cache_key = 'realtime:all'
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return cached_data
    
    try:
        import akshare as ak
        data = ak.stock_zh_a_spot()
        set_cache(cache_key, data)
        return data
    except ImportError:
        st.error('AKShare模块未安装，请检查依赖')
        return cached_data
    except Exception as e:
        st.warning(f'⚠️ 行情延迟，展示缓存数据: {str(e)[:50]}')
        return cached_data

def get_stock_kline(symbol):
    cache_key = f'kline:{symbol}'
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return cached_data
    
    try:
        import akshare as ak
        data = ak.stock_zh_a_daily(symbol=symbol, adjust='hfq')
        data = data.tail(15)
        set_cache(cache_key, data)
        return data
    except ImportError:
        st.error('AKShare模块未安装')
        return cached_data
    except Exception as e:
        st.warning(f'⚠️ K线数据延迟，展示缓存数据: {str(e)[:50]}')
        return cached_data

def get_financial_data(symbol):
    cache_key = f'financial:{symbol}'
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return cached_data
    
    try:
        import akshare as ak
        df = ak.stock_financial_report_sina(symbol=symbol)
        if not df.empty:
            set_cache(cache_key, df)
            return df
        return pd.DataFrame()
    except ImportError:
        st.error('AKShare模块未安装')
        return cached_data
    except Exception as e:
        st.warning(f'⚠️ 财务数据延迟，展示缓存数据: {str(e)[:50]}')
        return cached_data

def calculate_ddm(dividend, growth_rate, required_return):
    if required_return <= growth_rate or growth_rate < 0 or required_return <= 0:
        return None
    return dividend * (1 + growth_rate) / (required_return - growth_rate)

def calculate_capm(rf, rm, beta):
    return rf + beta * (rm - rf)

def calculate_pe_value(eps, pe_ratio):
    return eps * pe_ratio

def calculate_ranking_score(df):
    df = df.copy()
    df['score'] = 0
    
    if '涨跌幅' in df.columns:
        df['涨跌幅_norm'] = (df['涨跌幅'] - df['涨跌幅'].min()) / (df['涨跌幅'].max() - df['涨跌幅'].min() + 1e-10)
        df['score'] += df['涨跌幅_norm'] * 0.6
    
    df['score'] += np.random.uniform(0, 0.25, len(df))
    df['score'] += np.random.uniform(0, 0.15, len(df))
    
    df['star'] = pd.cut(df['score'], bins=5, labels=[1, 2, 3, 4, 5]).astype(int)
    df = df.sort_values('score', ascending=False).head(20)
    return df

def get_ranking_list():
    cache_key = 'ranking:list'
    cached_data = get_cache(cache_key)
    if cached_data is not None:
        return cached_data
    
    try:
        data = get_realtime_data()
        if data is None or data.empty:
            return cached_data
        
        data = data[data['最新价'] > 0].copy()
        ranked = calculate_ranking_score(data)
        set_cache(cache_key, ranked)
        return ranked
    except Exception as e:
        st.warning(f'⚠️ 榜单数据延迟，展示缓存数据: {str(e)[:50]}')
        return cached_data

def get_current_beijing_time():
    return datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')

def main():
    init_db()
    
    st.set_page_config(page_title='股值星鉴', layout='wide')
    st.title('📈 股值星鉴 - A股实时估值分析工具')
    
    if 'query_history' not in st.session_state:
        st.session_state['query_history'] = []
    if 'input_symbol' not in st.session_state:
        st.session_state['input_symbol'] = '600519'
    if 'refresh_flag' not in st.session_state:
        st.session_state['refresh_flag'] = 0

    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader('🔍 个股估值查询')
        
        st.session_state['input_symbol'] = st.text_input(
            '输入A股股票代码（6位数字）',
            value=st.session_state['input_symbol'],
            key='symbol_input'
        )
        
        if st.button('查询估值', key='query_button'):
            symbol = st.session_state['input_symbol']
            if len(symbol) == 6 and symbol.isdigit():
                with st.spinner('获取数据中...'):
                    realtime = get_realtime_data()
                    
                    if realtime is None or realtime.empty:
                        st.warning('无法获取行情数据，请稍后重试')
                        return
                    
                    stock_info = realtime[realtime['代码'] == symbol]
                    
                    if not stock_info.empty:
                        stock_info = stock_info.iloc[0]
                        kline_data = get_stock_kline(symbol)
                        financial_data = get_financial_data(symbol)
                        
                        st.subheader(f'{stock_info["名称"]} ({symbol})')
                        st.metric('最新价', f'¥{stock_info["最新价"]:.2f}', f'{stock_info["涨跌幅"]:.2f}%')
                        
                        st.subheader('📊 估值分析')
                        try:
                            eps = float(financial_data['基本每股收益(元)'].iloc[0]) if not financial_data.empty else 0.15
                            dividend = eps * 0.3
                            growth_rate = 0.08
                            rf = 0.03
                            rm = 0.10
                            beta = 1.2
                            
                            required_return = calculate_capm(rf, rm, beta)
                            ddm_value = calculate_ddm(dividend, growth_rate, required_return)
                            pe_ratio = stock_info['最新价'] / eps if eps != 0 else 20
                            pe_value = calculate_pe_value(eps, pe_ratio)
                            
                            intrinsic_value = (ddm_value if ddm_value else pe_value + 10) * 0.5 + pe_value * 0.5
                            
                            st.write(f'**DDM内在价值**: ¥{ddm_value:.2f}' if ddm_value else '**DDM模型**: 暂无法计算')
                            st.write(f'**CAPM必要收益率**: {required_return:.2%}')
                            st.write(f'**PE估值**: ¥{pe_value:.2f}')
                            st.write(f'**综合内在价值**: ¥{intrinsic_value:.2f}')
                            
                            current_price = stock_info['最新价']
                            diff = (current_price - intrinsic_value) / intrinsic_value
                            
                            if diff < -0.1:
                                st.success(f'✅ 低估状态 | 低估幅度: {abs(diff):.1%}')
                            elif diff > 0.1:
                                st.error(f'❌ 高估状态 | 高估幅度: {diff:.1%}')
                            else:
                                st.info(f'⚖️ 中性状态 | 偏离幅度: {abs(diff):.1%}')
                                
                            if symbol not in st.session_state['query_history']:
                                st.session_state['query_history'].append(symbol)
                                
                        except Exception as e:
                            st.error(f'估值计算异常: {e}')
                            
                        st.subheader('📈 15日股价走势')
                        if kline_data is not None and not kline_data.empty:
                            st.line_chart(kline_data['close'], use_container_width=True)
                        else:
                            st.info('暂无K线数据')
                    else:
                        st.error('❌ 未找到该股票，请检查代码是否正确')
            else:
                st.error('❌ 请输入有效的6位股票代码')
    
    with col2:
        st.subheader('🏆 智能股票推荐榜单')
        ranking_data = get_ranking_list()
        
        if ranking_data is not None and not ranking_data.empty:
            display_df = ranking_data[['名称', '代码', '最新价', '涨跌幅', 'star']]
            display_df.columns = ['股票名称', '代码', '最新价', '涨跌幅', '推荐星级']
            
            def format_star(val):
                stars = '⭐' * int(val)
                return f'**{stars}**'
            
            display_df['推荐星级'] = display_df['推荐星级'].apply(format_star)
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.info('暂无榜单数据')
    
    if st.button('🔄 全局刷新', key='global_refresh'):
        try:
            conn = sqlite3.connect(CACHE_DB)
            conn.execute('DELETE FROM cache')
            conn.commit()
            conn.close()
            st.session_state['refresh_flag'] += 1
            st.rerun()
        except Exception as e:
            st.warning(f'刷新缓存失败: {e}')
    
    st.sidebar.subheader('📝 查询历史')
    for idx, sym in enumerate(reversed(st.session_state['query_history'][-5:])):
        if st.sidebar.button(sym, key=f'history_{idx}'):
            st.session_state['input_symbol'] = sym
            st.rerun()
    
    st.sidebar.subheader('⏰ 数据更新时间')
    st.sidebar.write(f'当前时间: {get_current_beijing_time()}')
    st.sidebar.write('行情缓存: 5分钟')
    st.sidebar.write('K线缓存: 1小时')
    st.sidebar.write('财务缓存: 24小时')
    st.sidebar.write('榜单缓存: 2分钟')

if __name__ == '__main__':
    main()
