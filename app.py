import json
import os
from flask import Flask, render_template, jsonify
import requests
from requests.exceptions import RequestException, ConnectionError, Timeout
from datetime import datetime
from ping3 import ping
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from cachetools import cached, TTLCache

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVICES_CONFIG = os.environ.get('SERVICES_CONFIG', 'services.conf')

cache = TTLCache(maxsize=1, ttl=3)

def load_services_and_groups():
    """Загружает конфигурацию и возвращает список групп."""
    if not os.path.exists(SERVICES_CONFIG):
        logger.error(f"Файл {SERVICES_CONFIG} не найден.")
        return []

    try:
        with open(SERVICES_CONFIG, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга JSON: {e}")
        return []
    except IOError as e:
        logger.error(f"Ошибка чтения файла: {e}")
        return []

    groups = []

    # Старый формат (список сервисов)
    if isinstance(data, list):
        valid_services = []
        for idx, s in enumerate(data):
            if not isinstance(s, dict):
                continue
            if 'name' not in s:
                continue
            if 'url' not in s and 'ip' not in s:
                continue
            s.setdefault('category', 'Other')
            s.setdefault('verify_ssl', True)
            s.setdefault('icon', 'mdi:server')
            valid_services.append(s)
        if valid_services:
            groups.append({'name': 'Все сервисы', 'services': valid_services})
        return groups

    # Новый формат с groups
    if isinstance(data, dict):
        groups_data = data.get('groups', [])
        for group in groups_data:
            if not isinstance(group, dict):
                continue
            group_name = group.get('name', 'Group')
            services = group.get('services', [])
            valid_services = []
            for s in services:
                if not isinstance(s, dict):
                    continue
                if 'name' not in s:
                    continue
                if 'url' not in s and 'ip' not in s:
                    continue
                s.setdefault('category', 'Other')
                s.setdefault('verify_ssl', True)
                s.setdefault('icon', 'mdi:server')
                valid_services.append(s)
            if valid_services:
                groups.append({'name': group_name, 'services': valid_services})
        return groups

    logger.error("Неизвестный формат конфигурации")
    return []

def get_all_services(groups):
    services = []
    for g in groups:
        services.extend(g['services'])
    return services

def check_http(url, verify_ssl=True):
    if not url:
        return None
    try:
        requests.get(url, timeout=1.5, verify=verify_ssl, allow_redirects=True)
        return True
    except (ConnectionError, Timeout, RequestException):
        return False

def check_ping(host):
    if not host:
        return None
    try:
        if ':' in host:
            host = host.split(':')[0]
        response = ping(host, timeout=1, unit='ms')
        return response is not None
    except Exception:
        return False

def check_service_availability(service):
    url = service.get('url')
    ip = service.get('ip')
    verify_ssl = service.get('verify_ssl', True)

    http_ok = check_http(url, verify_ssl) if url else None
    ping_ok = check_ping(ip) if ip else None

    if url and ip:
        available = (http_ok is True) or (ping_ok is True)
    elif url:
        available = http_ok is True
    elif ip:
        available = ping_ok is True
    else:
        available = False

    return {'available': available, 'http': http_ok, 'ping': ping_ok}

@cached(cache)
def get_cached_statuses():
    groups = load_services_and_groups()
    services = get_all_services(groups)
    services_status = []
    available_count = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_service = {executor.submit(check_service_availability, s): s for s in services}
        for future in as_completed(future_to_service):
            service = future_to_service[future]
            try:
                status_info = future.result()
            except Exception as e:
                logger.error(f"Ошибка проверки {service.get('name')}: {e}")
                status_info = {'available': False, 'http': None, 'ping': None}

            if status_info['available']:
                available_count += 1
            services_status.append({
                'name': service['name'],
                'available': status_info['available'],
                'http': status_info['http'],
                'ping': status_info['ping']
            })

    return {
        'services': services_status,
        'total': len(services_status),
        'available': available_count,
        'timestamp': datetime.now().isoformat()
    }

@app.route('/')
def homepage():
    groups = load_services_and_groups()
    for group in groups:
        for service in group['services']:
            service['available'] = None
            service['http'] = None
            service['ping'] = None

    return render_template('home.html', groups=groups)

@app.route('/api/status')
def api_status():
    return jsonify(get_cached_statuses())

@app.errorhandler(404)
def not_found_error(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)