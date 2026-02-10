import Image from 'next/image';
import React from 'react';

const Header = () => {
  return (
    <header className="bg-[f5f5f5] text-white p-6 flex justify-between items-center">
      <Image src="/assets/logo.png" alt="quantus logo" width={150} height={150} />
    </header>
  );
};

export default Header;
