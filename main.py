import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
from database.db import init_db
from config import load_config

# Настройка логгера с выводом в консоль
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("escrow_bot")

load_dotenv()

async def main():
    try:
        logger.info("🚀 Начинаем запуск бота...")
        
        config = load_config()
        logger.debug(f"Загружены настройки: {config.__dict__}")
        
        # Проверка токена
        if not config.bot_token or len(config.bot_token) < 10:
            logger.error("❌ ОШИБКА: Неверный токен бота. Проверьте файл .env")
            return
        
        logger.info("🔄 Инициализируем базу данных...")
        await init_db()
        
        bot = Bot(token=config.bot_token)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)
        
        # Динамический импорт обработчиков
        try:
            logger.info("🔄 Подключаем обработчики...")
            from handlers import start, deal_creation, deal_verification, admin, main_menu, user_actions  # ДОБАВЛЕН user_actions
            
            # Проверка наличия роутеров
            for handler_name, handler in [
                ("start", start),
                ("deal_creation", deal_creation),
                ("deal_verification", deal_verification),
                ("admin", admin),
                ("main_menu", main_menu),
                ("user_actions", user_actions)  # ДОБАВЛЕН в список проверки
            ]:
                if hasattr(handler, 'router'):
                    logger.debug(f"✅ Подключен роутер: {handler_name}")
                    dp.include_router(handler.router)
                else:
                    logger.error(f"❌ Ошибка: Нет атрибута router в {handler_name}")
            
            logger.info("✅ Все обработчики подключены")
            
        except Exception as e:
            logger.exception(f"❌ Ошибка при подключении обработчиков: {str(e)}")
            return
        
        logger.info("✅ Бот полностью настроен")
        logger.info("🌐 Начинаем polling...")
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.exception(f"❌ Критическая ошибка при запуске: {str(e)}")
        raise

if __name__ == "__main__":
    logger.info("✨ Запуск Escrow Bot")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.exception(f"❌ Необработанная ошибка: {str(e)}")
    finally:
        logger.info("ℹ️ Работа завершена")