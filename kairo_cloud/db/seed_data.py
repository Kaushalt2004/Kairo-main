import asyncio
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal, Base, engine
from app.core.security import get_password_hash, hash_api_key
from app.models import Organization, User, UserRole, Vehicle, VehicleStatus


async def seed():
    print("Beginning database seeding for Kairo Cloud...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Organization
        stmt = select(Organization).where(Organization.id == "org_default")
        res = await db.execute(stmt)
        org = res.scalar_one_or_none()
        if not org:
            org = Organization(id="org_default", name="Kairo Autonomous Mobility Labs")
            db.add(org)
            await db.commit()
            print("Created default organization.")

        # 2. Users
        users = [
            ("admin@kairo.ai", "AdminPass123!", "Kairo Fleet Admin", UserRole.ADMIN),
            ("operator@kairo.ai", "OperatorPass123!", "Mission Control Operator", UserRole.OPERATOR),
            ("viewer@kairo.ai", "ViewerPass123!", "Safety Observer", UserRole.VIEWER),
        ]
        for email, pwd, name, role in users:
            stmt = select(User).where(User.email == email)
            res = await db.execute(stmt)
            if not res.scalar_one_or_none():
                u = User(
                    email=email,
                    hashed_password=get_password_hash(pwd),
                    full_name=name,
                    role=role,
                    org_id="org_default",
                    is_active=True
                )
                db.add(u)
                print(f"Created user: {email} ({role.value})")

        # 3. Vehicles
        vehicles_seed = [
            (
                "KAIRO-001",
                "Apollo Lincoln MKZ",
                "1FA6P8CF5H5000001",
                "Lincoln MKZ",
                "CARLA",
                "kairo_live_vehicle_kairo_001_key_secret_123"
            ),
            (
                "KAIRO-002",
                "CyberTruck Autonomous Testbed",
                "1FA6P8CF5H5000002",
                "Tesla Cybertruck",
                "Apollo",
                "kairo_live_vehicle_kairo_002_key_secret_456"
            )
        ]
        for vid, name, vin, model, sim_type, plain_key in vehicles_seed:
            stmt = select(Vehicle).where(Vehicle.id == vid)
            res = await db.execute(stmt)
            if not res.scalar_one_or_none():
                v = Vehicle(
                    id=vid,
                    org_id="org_default",
                    name=name,
                    vin=vin,
                    model=model,
                    simulator_type=sim_type,
                    api_key_hash=hash_api_key(plain_key),
                    status=VehicleStatus.OFFLINE,
                    is_active=True
                )
                db.add(v)
                print(f"Created vehicle: {vid} with API Key: {plain_key}")

        await db.commit()
    print("Database seeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(seed())
