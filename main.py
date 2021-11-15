import requests
from bs4 import BeautifulSoup
import csv
import os

URL = 'https://www.detmir.ru/catalog/index/name/lego/'
HEADERS = {
    'accept': 'text/html',
    'application/xhtml+xml': 'application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'accept-encoding': 'gzip, deflate, br',
    'accept-language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7,zh-TW;q=0.6,zh;q=0.5',
    'cache-control': 'max-age=0',
    'if-none-match': 'W/"1def7f-BcDKQQ2EqgGYlbZfxjAmEPbMo+c"',
    'referer': 'https://www.google.com/',
    'sec-ch-ua': '"Google Chrome";v="95", "Chromium";v="95", ";Not A Brand";v="99"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"Windows"',
    'sec-fetch-dest': 'document',
    'sec-fetch-mode': 'navigate',
    'sec-fetch-site': 'cross-site',
    'sec-fetch-user': '?1',
    'upgrade-insecure-requests': '1',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36'
}
HOST = 'https://www.detmir.ru'
FILE = 'toys.csv'


def get_html(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params)
    return r


def get_content(html):  # получает контент
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.find_all('div', class_='y_6')
    toys = []

    for item in items:
        price = item.find('p', class_='Oy')
        promo_price = item.find('p', class_='Ox')
        print(price)
        if price is None:
            price = "Нет Цены"
        else:
            price = price.get_text().replace('\xa0₽', '')
        if promo_price is None:
            promo_price = "Нет промо цены"
        else:
            promo_price = promo_price.get_text().replace('\xa0₽', '') # редактируем строку чтобы были чистые данные
        title = item.find('p', class_='Om').get_text(strip=True).replace('(', '').replace(')', '') # убираем лишние скобки
        link = item.find('a', class_='Oj')

        toys.append({
            'id': title[-5:],
            'title': title[:-5], # записываем все считанные данные
            'price': price,
            'city': soup.find('span', class_='vZ').get_text(),
            'promo_price': promo_price,
            'link': link.get('href'),
        })

    if len(toys) == 0: # если данных нет значит страницы закончились
        return 1
    else:
        return toys


def save_file(items, path): # записываем все данные в файл csv
    with open(path, 'w', newline='') as file:
        writer = csv.writer(file, delimiter=',')
        writer.writerow(['ID', 'Название', 'Цена', 'Город', 'Промо цена', 'Ссылка'])
        for item in items:
            writer.writerow([item['id'], item['title'], item['price'], item['city'], item['promo_price'], item['link']])


def parse():
    pageNumber = 2
    toys = []
    html = get_html(URL)

    soup = BeautifulSoup(html.text, 'html.parser')
    if html.status_code == 200:
        page = soup.find_all('button', class_='lS gy lW ma l_1 mj mh l_4')
        while page != '': # пока есть кнопка показать еще
            r = get_content(html.text)
            if r == 1: # если вернет единицу то выйдет из цикла
                print("Страницы закончились")
                break
            print(f'Парсинг страницы {pageNumber} ...')
            html = get_html(URL + f'page/{pageNumber}/')
            pageNumber += 1
            toys.extend(r)
        save_file(toys, FILE)
        print(f'Получено {len(toys)} товаров')
    else:
        print("Error find page")


parse()
