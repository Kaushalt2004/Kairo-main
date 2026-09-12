import asyncio
import os
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Setup test environment variables before importing app
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["SECRET_KEY"] = "test_secret_key_for_kairo_cloud_integration_testing_32b"
os.environ["PROJECT_NAME"] = "Kairo Cloud Test"

from app.main import app
from app.core.database import Base, get_db
from app.core.security import create_access_token, get_password_hash, hash_api_key
from app.models import User, UserRole, Vehicle, VehicleStatus


from sqlalchemy.pool import StaticPool
from httpx import ASGITransport, AsyncClient

# Test SQLite async engine with StaticPool so all connections share the in-memory database
test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False
)
TestSessionLocal = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with TestSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = override_get_db
transport = ASGITransport(app=app)


import pytest_asyncio


@pytest_asyncio.fixture(autouse=True)
async def setup_test_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Seed admin user and test vehicle
    async with TestSessionLocal() as db:
        admin = User(
            id="usr_admin_test",
            email="admin@test.ai",
            hashed_password=get_password_hash("AdminPass123!"),
            full_name="Admin Tester",
            role=UserRole.ADMIN,
            is_active=True
        )
        vehicle = Vehicle(
            id="KAIRO-TEST-001",
            name="Test Lincoln MKZ",
            simulator_type="CARLA",
            api_key_hash=hash_api_key("test_api_key_12345"),
            status=VehicleStatus.ONLINE,
            is_active=True
        )
        db.add(admin)
        db.add(vehicle)
        await db.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "kairo-cloud-backend"


@pytest.mark.asyncio
async def test_user_login():
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v1/auth/login", json={
            "email": "admin@test.ai",
            "password": "AdminPass123!"
        })
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" == "access_token"
    assert token_data["role"] == "ADMIN"
    assert token_data["email"] == "admin@test.ai"


@pytest.mark.asyncio
async def test_vehicle_registration():
    admin_token = create_access_token(subject="usr_admin_test", role="ADMIN")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/vehicles/register",
            json={
                "id": "KAIRO-003",
                "name": "Heavy Duty Robotruck",
                "model": "Volvo VNL Autoware",
                "simulator_type": "Apollo"
            },
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    assert response.status_code == 201
    res = response.json()
    assert res["success"] is True
    assert res["data"]["id"] == "KAIRO-003"
    assert "api_key" in res["data"]
    assert res["data"]["api_key"].startswith("kairo_")


@pytest.mark.asyncio
async def test_telemetry_rest_fallback_and_query():
    # Ingest telemetry via HTTP with API key
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ingest_res = await ac.post(
            "/api/v1/telemetry/KAIRO-TEST-001/ingest",
            headers={"X-API-Key": "test_api_key_12345"},
            json={
                "vehicle_id": "KAIRO-TEST-001",
                "location": {"latitude": 37.7749, "longitude": -122.4194, "altitude": 10.0, "heading": 180.0},
                "kinematics": {"speed": 12.5, "speed_kmh": 45.0, "acceleration": 0.5},
                "controls": {"steering": 0.05, "throttle": 0.3, "brake": 0.0, "gear": "D"},
                "compute": {"cpu_usage": 35.0, "gpu_usage": 60.0, "memory_usage": 40.0, "temperature_c": 50.0},
                "autonomy": {"mode": "AUTONOMOUS", "status": "ACTIVE", "target_speed_kmh": 45.0},
                "sensors": [
                    {"name": "front_camera", "sensor_type": "CAMERA", "status": "ONLINE", "fps": 30.0, "latency_ms": 12.0}
                ]
            }
        )
    assert ingest_res.status_code == 200
    assert ingest_res.json()["success"] is True

    # Query latest telemetry
    admin_token = create_access_token(subject="usr_admin_test", role="ADMIN")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        query_res = await ac.get(
            "/api/v1/telemetry/KAIRO-TEST-001/latest",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
    assert query_res.status_code == 200
    tel_data = query_res.json()["data"]
    assert tel_data["vehicle_id"] == "KAIRO-TEST-001"
    assert tel_data["kinematics"]["speed_kmh"] == 45.0


@pytest.mark.asyncio
async def test_command_validation_and_dispatch():
    admin_token = create_access_token(subject="usr_admin_test", role="ADMIN")
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Valid command
        cmd_res = await ac.post(
            "/api/v1/commands/KAIRO-TEST-001",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "command_type": "CHANGE_WEATHER",
                "parameters": {"weather": "ClearNoon"}
            }
        )
        assert cmd_res.status_code == 202
        assert cmd_res.json()["data"]["command_type"] == "CHANGE_WEATHER"

        # Invalid weather preset rejection
        bad_res = await ac.post(
            "/api/v1/commands/KAIRO-TEST-001",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "command_type": "CHANGE_WEATHER",
                "parameters": {"weather": "TornadoHurricaneInvalid"}
            }
        )
        assert bad_res.status_code == 422
