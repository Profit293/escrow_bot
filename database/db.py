import aiosqlite
import json
from pathlib import Path
from config import load_config
from datetime import datetime, timedelta
import logging

config = load_config()
DB_PATH = config.database_path
logger = logging.getLogger("escrow_bot")

async def init_db():
    """Creates or updates SQLite database"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Create deposit_addresses table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS deposit_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crypto_type TEXT NOT NULL CHECK(crypto_type IN ('BTC', 'LTC')),
            address TEXT UNIQUE NOT NULL,
            is_used BOOLEAN DEFAULT 0,
            reserved_until TIMESTAMP NULL
        )
        """)
        
        # Create users table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Create admins table
        await db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY
        )
        """)
        
        # Check and update deals table structure
        try:
            # Check current table structure
            cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='deals'")
            table_info = await cursor.fetchone()
            
            if table_info:
                table_sql = table_info[0]
                # Check current description constraint
                if "LENGTH(description) <= 100" in table_sql:
                    logger.info("🔄 Found old description length constraint (100 characters). Updating to 200...")
                    
                    # Create temporary table
                    await db.execute("""
                    CREATE TABLE deals_temp (
                        id TEXT PRIMARY KEY,
                        buyer_id INTEGER NOT NULL,
                        seller_id INTEGER NOT NULL,
                        crypto_type TEXT CHECK(crypto_type IN ('BTC', 'LTC')),
                        original_amount REAL NOT NULL,
                        amount REAL NOT NULL,
                        description TEXT CHECK(LENGTH(description) <= 200),
                        status TEXT DEFAULT 'CREATED',
                        deposit_address TEXT NOT NULL,
                        tx_hash TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """)
                    
                    # Copy data
                    await db.execute("""
                    INSERT INTO deals_temp
                    SELECT id, buyer_id, 
                           (SELECT id FROM users WHERE username = seller_username LIMIT 1),
                           crypto_type, amount, amount, description, status, deposit_address, tx_hash, 
                           created_at, updated_at
                    FROM deals
                    """)
                    
                    # Drop old table
                    await db.execute("DROP TABLE deals")
                    
                    # Rename temporary table
                    await db.execute("ALTER TABLE deals_temp RENAME TO deals")
                    
                    logger.info("✅ Deals table structure successfully updated to 200 characters")
                elif "seller_id" not in table_sql:
                    logger.warning("⚠️ No seller_id field. Updating structure...")
                    
                    # Create temporary table with new structure
                    await db.execute("""
                    CREATE TABLE deals_temp (
                        id TEXT PRIMARY KEY,
                        buyer_id INTEGER NOT NULL,
                        seller_id INTEGER NOT NULL,
                        crypto_type TEXT CHECK(crypto_type IN ('BTC', 'LTC')),
                        original_amount REAL NOT NULL,
                        amount REAL NOT NULL,
                        description TEXT CHECK(LENGTH(description) <= 200),
                        status TEXT DEFAULT 'CREATED',
                        deposit_address TEXT NOT NULL,
                        tx_hash TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """)
                    
                    # Copy data
                    await db.execute("""
                    INSERT INTO deals_temp
                    SELECT id, buyer_id, 
                           (SELECT id FROM users WHERE username = seller_username LIMIT 1),
                           crypto_type, amount, amount, description, status, deposit_address, tx_hash, 
                           created_at, updated_at
                    FROM deals
                    """)
                    
                    # Drop old table
                    await db.execute("DROP TABLE deals")
                    
                    # Rename temporary table
                    await db.execute("ALTER TABLE deals_temp RENAME TO deals")
                    
                    logger.info("✅ Added seller_id field to deals table structure")
            else:
                # Table doesn't exist, create new one with correct structure
                await db.execute("""
                CREATE TABLE deals (
                    id TEXT PRIMARY KEY,
                    buyer_id INTEGER NOT NULL,
                    seller_id INTEGER NOT NULL,
                    crypto_type TEXT CHECK(crypto_type IN ('BTC', 'LTC')),
                    original_amount REAL NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT CHECK(LENGTH(description) <= 200),
                    status TEXT DEFAULT 'CREATED',
                    deposit_address TEXT NOT NULL,
                    tx_hash TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                logger.info("✅ Created new deals table with 200 character constraint")
        
        except Exception as e:
            logger.error(f"❌ Error checking/updating deals table structure: {str(e)}")
            # Create table with correct structure as last resort
            await db.execute("DROP TABLE IF EXISTS deals")
            await db.execute("""
            CREATE TABLE deals (
                id TEXT PRIMARY KEY,
                buyer_id INTEGER NOT NULL,
                seller_id INTEGER NOT NULL,
                crypto_type TEXT CHECK(crypto_type IN ('BTC', 'LTC')),
                original_amount REAL NOT NULL,
                amount REAL NOT NULL,
                description TEXT CHECK(LENGTH(description) <= 200),
                status TEXT DEFAULT 'CREATED',
                deposit_address TEXT NOT NULL,
                tx_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            logger.info("✅ Deals table recreated with correct structure")
        
        # Load address pool from JSON
        addresses_file = Path("deposit_addresses.json")
        if addresses_file.exists():
            with open(addresses_file) as f:
                addresses = json.load(f)
            
            for crypto, addr_list in addresses.items():
                # Ensure we only add BTC and LTC
                if crypto in ["BTC", "LTC"]:
                    for addr in addr_list:
                        await db.execute(
                            "INSERT OR IGNORE INTO deposit_addresses (crypto_type, address) VALUES (?, ?)",
                            (crypto, addr)
                        )
        
        # Add admins
        for admin_id in config.admin_telegram_ids:
            await db.execute(
                "INSERT OR IGNORE INTO admins (telegram_id) VALUES (?)",
                (admin_id,)
            )
        
        await db.commit()
        logger.info("✅ Database successfully initialized")

async def release_expired_addresses():
    """Releases addresses reserved more than 12 hours ago"""
    async with aiosqlite.connect(DB_PATH) as db:
        current_time = datetime.utcnow()
        expired_time = current_time - timedelta(hours=12)
        
        # Update addresses with expired reservation time
        await db.execute("""
        UPDATE deposit_addresses
        SET is_used = 0, reserved_until = NULL
        WHERE reserved_until IS NOT NULL AND reserved_until < ?
        AND address NOT IN (
            SELECT deposit_address FROM deals 
            WHERE status IN ('PAID', 'SHIPPED', 'COMPLETED')
        )
        """, (expired_time,))
        
        rows_affected = db.total_changes
        if rows_affected > 0:
            logger.info(f"✅ Released {rows_affected} addresses with expired reservation")
        
        await db.commit()

async def get_next_deposit_address(crypto_type: str) -> str:
    """Returns a free address from the pool (with automatic release)"""
    # Check allowed cryptocurrency types
    if crypto_type not in ["BTC", "LTC"]:
        raise ValueError("Only BTC and LTC are allowed")
    
    # First release expired addresses
    await release_expired_addresses()
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Get address with earliest reservation time
        cursor = await db.execute(
            """
            SELECT address FROM deposit_addresses 
            WHERE crypto_type = ? AND (
                is_used = 0 OR 
                reserved_until < datetime('now')
            )
            ORDER BY 
                CASE WHEN is_used = 0 THEN 0 ELSE 1 END,
                reserved_until ASC
            LIMIT 1
            """,
            (crypto_type,)
        )
        row = await cursor.fetchone()
        
        if not row:
            raise ValueError(f"No free addresses for {crypto_type}. Contact administrator.")
        
        address = row[0]
        
        # Update status and set reservation time
        reserved_until = datetime.utcnow() + timedelta(hours=12)
        await db.execute(
            """
            UPDATE deposit_addresses 
            SET is_used = 1, reserved_until = ? 
            WHERE address = ?
            """,
            (reserved_until, address)
        )
        await db.commit()
        return address

async def create_user(telegram_id: int, username: str):
    """Creates a user in the database"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (telegram_id, username) VALUES (?, ?)",
            (telegram_id, username)
        )
        await db.commit()

async def get_user_by_username(username: str) -> dict:
    """Gets a user by username"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?",
            (username,)
        )
        row = await cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

async def get_user_by_id(user_id: int) -> dict:
    """Gets a user by ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM users WHERE id = ? OR telegram_id = ?",
            (user_id, user_id)
        )
        row = await cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

async def create_deal(deal_data: dict):
    """Creates a new deal"""
    # Check cryptocurrency type
    if deal_data["crypto_type"] not in ["BTC", "LTC"]:
        raise ValueError("Only BTC and LTC are allowed")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
        INSERT INTO deals (
            id, buyer_id, seller_id, crypto_type, original_amount, amount,
            description, deposit_address, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            deal_data["id"],
            deal_data["buyer_id"],
            deal_data["seller_id"],
            deal_data["crypto_type"],
            deal_data["original_amount"],
            deal_data["amount"],
            deal_data["description"],
            deal_data["deposit_address"],
            deal_data["status"]
        ))
        await db.commit()

async def get_deal_by_id(deal_id: str) -> dict:
    """Gets a deal by ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT * FROM deals WHERE id = ?",
            (deal_id,)
        )
        row = await cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, row))
        return None

async def update_deal_status(deal_id: str, new_status: str, tx_hash: str = None):
    """Updates deal status and update time"""
    async with aiosqlite.connect(DB_PATH) as db:
        if tx_hash:
            await db.execute(
                "UPDATE deals SET status = ?, tx_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_status, tx_hash, deal_id)
            )
        else:
            await db.execute(
                "UPDATE deals SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_status, deal_id)
            )
        await db.commit()

async def has_available_addresses(crypto_type: str) -> bool:
    """Checks for available addresses"""
    # Check allowed cryptocurrency types
    if crypto_type not in ["BTC", "LTC"]:
        return False
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM deposit_addresses WHERE crypto_type = ? AND is_used = 0 LIMIT 1",
            (crypto_type,)
        )
        return bool(await cursor.fetchone())