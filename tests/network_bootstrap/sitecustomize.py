"""Test-only network barrier, loaded by Python before test or app imports."""
import network_fence

network_fence.install()
